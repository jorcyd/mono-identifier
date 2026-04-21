"""Re-ranking visual: compara a imagem original com renderizações das fontes candidatas.

Para cada fonte do catálogo (que seja renderizável), a gente:
    1. Baixa o TTF (Google Fonts via CSS API ou URL direta), cacheando em disco.
    2. Renderiza o texto extraído pelo upstream como imagem em preto sobre branco.
    3. Alinha essa renderização com a imagem original via template matching,
       varrendo escala para encontrar o melhor fit.
    4. Calcula similaridade combinada: SSIM + IoU de bordas.
    5. Re-ordena candidatos e promove o top-1 se a diferença for significativa.

Fontes não renderizáveis (pagas / distribuição restrita) são preservadas na
ordem original com `visual_similarity=None` e flag `renderable=False`.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv2
import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.metrics import structural_similarity as ssim

from config import get_settings
from fonts_catalog import FontEntry, lookup

log = logging.getLogger(__name__)

# Thresholds
PROMOTE_MARGIN = 0.08           # top-1 visual precisa superar atual por isso pra virar primary
SSIM_WEIGHT = 0.6
EDGE_WEIGHT = 0.4

# Budget de texto para rendering (performance)
MAX_RENDER_LINES = 10
MAX_RENDER_COLS = 80


@dataclass
class ScoredCandidate:
    name: str
    original: dict              # payload original do upstream
    entry: Optional[FontEntry]  # match no catálogo (None = desconhecida)
    visual_similarity: Optional[float]  # 0..1 ou None se não renderizável
    components: dict            # {ssim, edge_iou, best_scale}


async def rerank_candidates(
    upstream_response: dict[str, Any],
    reference_gray: np.ndarray,
) -> dict[str, Any]:
    """Recebe a resposta do upstream e a imagem de referência (grayscale,
    preprocessada). Retorna a resposta com candidatos re-ranqueados e campos
    adicionais (`visual_similarity`, `renderable`, `quality`).

    A ordem dos candidatos pode ser reorganizada. Se o melhor candidato visual
    ultrapassar o primary atual por PROMOTE_MARGIN, ele vira o novo primary.
    """
    primary = upstream_response.get("primary_match") or {}
    alternatives = upstream_response.get("alternatives") or []
    extracted_code = upstream_response.get("extracted_code") or ""

    ordered: list[dict] = []
    if primary.get("name"):
        ordered.append(primary)
    ordered.extend(alternatives)

    if not ordered or not extracted_code.strip():
        # Sem o que comparar — devolve original com flags defaults
        return _annotate_untouched(upstream_response, reason="no_candidates_or_code")

    # Normaliza texto (limita tamanho)
    rendered_text = _truncate_code(extracted_code)
    ref_gray_norm = _normalize_gray(reference_gray)

    # Computa similaridade em paralelo para todos os candidatos
    tasks = [
        _score_candidate(c, rendered_text, ref_gray_norm) for c in ordered
    ]
    scored: list[ScoredCandidate] = await asyncio.gather(*tasks)

    # Separa renderizáveis dos não-renderizáveis
    renderable = [s for s in scored if s.visual_similarity is not None]
    non_renderable = [s for s in scored if s.visual_similarity is None]

    # Ordena renderáveis por similaridade (desc)
    renderable.sort(key=lambda s: s.visual_similarity, reverse=True)

    # Decide novo primary
    new_primary, new_alternatives = _decide_order(ordered, renderable, non_renderable, primary)

    # Recalibra confidence: mistura upstream + visual
    for cand_payload, scored_item in _pair(new_primary, new_alternatives, scored):
        _apply_visual_fields(cand_payload, scored_item)

    result = dict(upstream_response)
    result["primary_match"] = new_primary
    result["alternatives"] = new_alternatives
    result["rerank"] = {
        "applied": True,
        "promoted": new_primary.get("name") != primary.get("name"),
        "total_candidates": len(ordered),
        "renderable_candidates": len(renderable),
    }
    return result


def _annotate_untouched(response: dict, reason: str) -> dict:
    result = dict(response)
    result["rerank"] = {"applied": False, "reason": reason}
    # mesmo assim marca `renderable` pra UI
    for c in [result.get("primary_match") or {}] + (result.get("alternatives") or []):
        if not c:
            continue
        entry = lookup(c.get("name", ""))
        c["renderable"] = bool(entry and entry.renderable)
        c.setdefault("visual_similarity", None)
    return result


async def _score_candidate(
    candidate: dict, rendered_text: str, ref_gray_norm: np.ndarray,
) -> ScoredCandidate:
    name = candidate.get("name") or ""
    entry = lookup(name)

    if not entry or not entry.renderable:
        return ScoredCandidate(
            name=name, original=candidate, entry=entry,
            visual_similarity=None, components={"reason": "not_renderable"},
        )

    try:
        ttf_path = await _ensure_ttf(entry)
    except Exception as e:
        log.warning("falha baixando TTF de %s: %s", name, e)
        return ScoredCandidate(
            name=name, original=candidate, entry=entry,
            visual_similarity=None, components={"reason": f"download_failed: {e}"},
        )

    # Render: gera imagem preto sobre branco do texto com essa fonte
    try:
        render_gray = _render_text(rendered_text, ttf_path, target_height=ref_gray_norm.shape[0])
    except Exception as e:
        log.warning("falha renderizando %s: %s", name, e)
        return ScoredCandidate(
            name=name, original=candidate, entry=entry,
            visual_similarity=None, components={"reason": f"render_failed: {e}"},
        )

    sim, components = _compare(ref_gray_norm, render_gray)
    return ScoredCandidate(
        name=name, original=candidate, entry=entry,
        visual_similarity=sim, components=components,
    )


def _decide_order(
    ordered: list[dict],
    renderable: list[ScoredCandidate],
    non_renderable: list[ScoredCandidate],
    original_primary: dict,
) -> tuple[dict, list[dict]]:
    """Ordem final:
        - Se o top renderável bate o primary atual por PROMOTE_MARGIN, promove.
        - Senão, mantém primary original mas re-ordena alternativas por similaridade.
        - Não-renderáveis ficam depois das renderáveis.
    """
    by_name = {id(c): c for c in ordered}
    original_primary_id = id(original_primary) if original_primary in ordered else None

    # Score do primary atual (se renderable)
    primary_sim = next(
        (s.visual_similarity for s in renderable if s.original is original_primary),
        None,
    )
    top_candidate = renderable[0] if renderable else None

    promote = (
        top_candidate is not None
        and top_candidate.original is not original_primary
        and (
            primary_sim is None
            or (top_candidate.visual_similarity - (primary_sim or 0)) >= PROMOTE_MARGIN
        )
    )

    final_order: list[dict] = []
    if promote:
        final_order.append(top_candidate.original)
        rest_renderable = [s.original for s in renderable if s.original is not top_candidate.original]
    else:
        # Primary fica, re-ordena o resto
        if original_primary in ordered:
            final_order.append(original_primary)
        rest_renderable = [s.original for s in renderable if s.original is not original_primary]

    final_order.extend(rest_renderable)
    final_order.extend(s.original for s in non_renderable if s.original not in final_order)

    return final_order[0], final_order[1:]


def _pair(primary: dict, alternatives: list[dict], scored: list[ScoredCandidate]):
    by_id = {id(s.original): s for s in scored}
    for c in [primary, *alternatives]:
        s = by_id.get(id(c))
        if s is not None:
            yield c, s


def _apply_visual_fields(payload: dict, scored: ScoredCandidate) -> None:
    entry = scored.entry
    payload["renderable"] = bool(entry and entry.renderable)
    payload["visual_similarity"] = (
        round(scored.visual_similarity, 4) if scored.visual_similarity is not None else None
    )
    if scored.visual_similarity is not None:
        # mistura: 70% visual, 30% upstream
        upstream_conf = float(payload.get("confidence") or 0.0)
        payload["confidence_upstream"] = round(upstream_conf, 4)
        mixed = 0.7 * scored.visual_similarity + 0.3 * upstream_conf
        payload["confidence"] = round(max(0.0, min(1.0, mixed)), 4)
    payload["rerank_details"] = scored.components


# --------------------------------------------------------------------------- #
# Rendering & metric helpers
# --------------------------------------------------------------------------- #

def _truncate_code(code: str) -> str:
    lines = [line[:MAX_RENDER_COLS] for line in code.splitlines()]
    lines = [line for line in lines if line.strip()][:MAX_RENDER_LINES]
    return "\n".join(lines) if lines else code[:MAX_RENDER_COLS * MAX_RENDER_LINES]


def _normalize_gray(gray: np.ndarray) -> np.ndarray:
    # Normalização min-max pra [0,255] uint8
    g = gray.astype(np.float32)
    mn, mx = g.min(), g.max()
    if mx - mn < 1:
        return gray.copy()
    g = (g - mn) * (255.0 / (mx - mn))
    return g.astype(np.uint8)


def _render_text(text: str, ttf_path: Path, target_height: int) -> np.ndarray:
    """Renderiza `text` com a fonte em PNG preto sobre branco.

    O tamanho do font é escolhido para aproximar a altura total de linha pelo
    lado da imagem de referência. Isso não precisa ser exato — o template
    matching depois varre escala ao redor.
    """
    # Chuta font size: target_height / num_lines ≈ altura por linha
    num_lines = max(1, text.count("\n") + 1)
    target_line_h = max(10, target_height // max(num_lines + 1, 4))
    font_size = max(10, int(target_line_h * 0.85))

    try:
        font = ImageFont.truetype(str(ttf_path), font_size)
    except Exception:
        # Alguns arquivos podem ser OTF; truetype cobre OTF no Pillow moderno,
        # mas se falhar propaga
        raise

    # Calcula bbox do texto
    tmp_img = Image.new("L", (10, 10), 255)
    draw = ImageDraw.Draw(tmp_img)
    # multiline: getbbox não cobre em versões antigas, usa textbbox
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=2)
    tw = max(1, bbox[2] - bbox[0])
    th = max(1, bbox[3] - bbox[1])

    margin = 4
    img = Image.new("L", (tw + 2 * margin, th + 2 * margin), 255)
    draw = ImageDraw.Draw(img)
    draw.multiline_text((margin - bbox[0], margin - bbox[1]), text, fill=0, font=font, spacing=2)

    return np.asarray(img)


def _compare(ref_gray: np.ndarray, render_gray: np.ndarray) -> tuple[float, dict]:
    """Alinha `render` sobre `ref` com template matching multi-escala,
    calcula SSIM + IoU de bordas na janela alinhada.
    """
    ref_bin = _binarize(ref_gray, invert_black_text=True)
    render_bin = _binarize(render_gray, invert_black_text=True)

    best_scale, best_ref_crop, best_ren_crop, best_ccoeff = _align(ref_bin, render_bin)
    if best_ref_crop is None or best_ren_crop is None:
        return 0.0, {"reason": "align_failed"}

    # Iguala tamanhos (o template matching já garante isso mas garante)
    h = min(best_ref_crop.shape[0], best_ren_crop.shape[0])
    w = min(best_ref_crop.shape[1], best_ren_crop.shape[1])
    ref_c = best_ref_crop[:h, :w]
    ren_c = best_ren_crop[:h, :w]

    if h < 8 or w < 8:
        return 0.0, {"reason": "too_small_after_align"}

    # SSIM nas versões em [0,1]
    try:
        ssim_val = float(ssim(ref_c, ren_c, data_range=255))
        ssim_val = max(0.0, min(1.0, (ssim_val + 1) / 2))  # mapeia [-1,1] → [0,1]
    except Exception as e:
        log.warning("SSIM falhou: %s", e)
        ssim_val = 0.0

    # IoU de bordas (Canny)
    ref_edges = cv2.Canny(ref_c, 60, 160)
    ren_edges = cv2.Canny(ren_c, 60, 160)
    inter = int(np.logical_and(ref_edges > 0, ren_edges > 0).sum())
    union = int(np.logical_or(ref_edges > 0, ren_edges > 0).sum())
    iou = (inter / union) if union > 0 else 0.0

    score = SSIM_WEIGHT * ssim_val + EDGE_WEIGHT * iou
    return float(score), {
        "ssim": round(ssim_val, 4),
        "edge_iou": round(iou, 4),
        "best_scale": round(best_scale, 3),
        "template_ccoeff": round(float(best_ccoeff), 4),
    }


def _binarize(gray: np.ndarray, invert_black_text: bool = True) -> np.ndarray:
    """Otsu binarization. Se `invert_black_text`, garante que o texto fique
    como pixels claros (255) sobre fundo escuro (0) pra facilitar edge+SSIM.
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if invert_black_text:
        # Se a maioria dos pixels é branca (fundo), assume texto em preto e inverte
        if np.mean(bw) > 127:
            bw = 255 - bw
    return bw


def _align(ref: np.ndarray, template: np.ndarray) -> tuple[float, Optional[np.ndarray], Optional[np.ndarray], float]:
    """Template matching multi-escala. Retorna (scale, ref_crop, template_resized, ccoeff)."""
    if ref.size == 0 or template.size == 0:
        return 1.0, None, None, 0.0

    ref_h, ref_w = ref.shape[:2]

    best = (1.0, None, None, -1.0)
    scales = np.arange(0.7, 1.51, 0.05)
    for s in scales:
        new_w = int(round(template.shape[1] * s))
        new_h = int(round(template.shape[0] * s))
        if new_w < 8 or new_h < 8 or new_w > ref_w or new_h > ref_h:
            continue
        resized = cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(ref, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best[3]:
            x, y = max_loc
            ref_crop = ref[y:y + new_h, x:x + new_w]
            best = (float(s), ref_crop, resized, float(max_val))

    return best


# --------------------------------------------------------------------------- #
# Download + cache de fontes
# --------------------------------------------------------------------------- #

_download_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    lock = _download_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _download_locks[key] = lock
    return lock


async def _ensure_ttf(entry: FontEntry) -> Path:
    settings = get_settings()
    safe = re.sub(r"[^A-Za-z0-9]+", "_", entry.canonical)
    filename = f"{safe}.ttf"
    dest = settings.fonts_cache_path / filename

    if dest.exists() and dest.stat().st_size > 1024:
        return dest

    async with _lock_for(entry.canonical):
        if dest.exists() and dest.stat().st_size > 1024:
            return dest

        if entry.source == "google":
            url = await _resolve_google_font_url(entry.canonical)
        elif entry.source == "url" and entry.ttf_url:
            url = entry.ttf_url
        else:
            raise RuntimeError(f"fonte {entry.canonical}: sem URL de download")

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code >= 400 or not resp.content:
            raise RuntimeError(f"download {url} → HTTP {resp.status_code}")

        dest.write_bytes(resp.content)
        return dest


async def _resolve_google_font_url(family: str) -> str:
    """Resolve a URL direta do TTF a partir do CSS da Google Fonts API.

    Requisitamos o CSS com um User-Agent que força a API a devolver TTF (sem
    user-agent moderno, volta WOFF2 que não é suportado pelo Pillow).
    """
    q = family.replace(" ", "+")
    url = f"https://fonts.googleapis.com/css2?family={q}:wght@400&display=swap"
    headers = {
        # User-Agent antigo força TTF na resposta
        "User-Agent": "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.0)",
    }
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code >= 400:
        raise RuntimeError(f"google fonts css {url} → HTTP {resp.status_code}")
    css = resp.text
    m = re.search(r"url\((https?://[^)]+\.ttf)\)", css)
    if not m:
        # fallback: tenta woff2 (Pillow >=10 tem suporte parcial via FreeType)
        m = re.search(r"url\((https?://[^)]+\.woff2?)\)", css)
    if not m:
        raise RuntimeError(f"não achei URL de fonte no CSS: {url}")
    return m.group(1)
