"""Preprocessamento de imagem antes de enviar ao upstream.

Pipeline:
    1. Decodifica para RGB.
    2. Upscale se lado maior < min_long_edge_for_upscale (Lanczos ou NN dependendo
       se parece pixelado ou renderizado com AA).
    3. Detecta tema e inverte se for fundo escuro (Claude Vision acerta mais em
       fundo claro).
    4. Aumenta contraste local com CLAHE (misturado 50/50 com o original).
    5. Unsharp mask leve.
    6. Reencoda PNG.

O resultado também é retornado como numpy array (grayscale) para alimentar o
pipeline de re-ranking, que precisa comparar contra a mesma versão preprocessada
que o upstream analisou.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageFilter

from config import get_settings


@dataclass
class PreprocessResult:
    png_bytes: bytes            # PNG a mandar pro upstream
    rgb: np.ndarray             # imagem preprocessada, HxWx3 uint8 (pro re-rank)
    gray: np.ndarray            # versão grayscale (pro re-rank)
    inverted: bool              # se invertemos (fundo escuro → claro)
    upscaled: float             # fator de upscale aplicado (1.0 = nenhum)
    quality: dict               # métricas para expor ao usuário


def preprocess(raw: bytes) -> PreprocessResult:
    settings = get_settings()

    img = Image.open(io.BytesIO(raw))
    img = _exif_transpose(img).convert("RGB")
    arr = np.asarray(img)  # HxWx3 uint8

    # 1. Upscale se pequeno
    upscale = 1.0
    h, w = arr.shape[:2]
    long_edge = max(h, w)
    if long_edge < settings.min_long_edge_for_upscale:
        target = settings.target_long_edge
        upscale = target / long_edge
        new_w = int(round(w * upscale))
        new_h = int(round(h * upscale))
        interp = _choose_interp(arr)
        arr = cv2.resize(arr, (new_w, new_h), interpolation=interp)

    # 2. Detecta tema (luminância mediana) e inverte se escuro
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    median_lum = float(np.median(gray)) / 255.0
    inverted = median_lum < 0.45
    if inverted:
        arr = 255 - arr
        gray = 255 - gray

    # 3. CLAHE em grayscale, mixado com o original (mantém cor sem distorcer demais)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray_eq = clahe.apply(gray)
    # Aplica o ganho de contraste no canal V do HSV pra não desaturar
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    v = hsv[:, :, 2]
    v_eq = clahe.apply(v)
    v_mix = cv2.addWeighted(v, 0.5, v_eq, 0.5, 0)
    hsv[:, :, 2] = v_mix
    arr = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)

    # 4. Unsharp mask leve (reforça bordas dos glifos)
    pil = Image.fromarray(arr)
    pil = pil.filter(ImageFilter.UnsharpMask(radius=1, percent=60, threshold=2))
    arr = np.asarray(pil)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # 5. Reencoda PNG
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", optimize=False)
    png_bytes = buf.getvalue()

    quality = _quality_metrics(gray, median_lum, upscale, inverted)

    return PreprocessResult(
        png_bytes=png_bytes,
        rgb=arr,
        gray=gray_eq,  # versão de alto contraste pro re-rank
        inverted=inverted,
        upscaled=upscale,
        quality=quality,
    )


def _exif_transpose(img: Image.Image) -> Image.Image:
    try:
        from PIL import ImageOps
        return ImageOps.exif_transpose(img)
    except Exception:
        return img


def _choose_interp(arr: np.ndarray) -> int:
    """NEAREST quando a imagem parece pixelada (poucos níveis de cinza nas
    bordas dos caracteres = screenshot de baixa-res sem AA). LANCZOS caso
    contrário.
    """
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    if not edges.any():
        return cv2.INTER_LANCZOS4
    # Conta níveis únicos numa vizinhança das bordas — se AA for pobre, poucos níveis.
    ys, xs = np.where(edges > 0)
    # amostra até 2000 pixels de borda pra ser rápido
    if len(ys) > 2000:
        idx = np.random.default_rng(0).choice(len(ys), size=2000, replace=False)
        ys, xs = ys[idx], xs[idx]
    vals = gray[ys, xs]
    unique = len(np.unique(vals))
    return cv2.INTER_NEAREST if unique < 20 else cv2.INTER_LANCZOS4


def _quality_metrics(gray: np.ndarray, median_lum: float, upscale: float, inverted: bool) -> dict:
    h, w = gray.shape[:2]
    # Estimativa tosca de contraste: desvio padrão do grayscale
    contrast = float(np.std(gray) / 255.0)
    # Estimativa tosca de nitidez: variância do laplaciano
    lap = cv2.Laplacian(gray, cv2.CV_64F).var()
    sharpness = float(min(lap / 500.0, 1.0))  # normaliza pra [0,1]
    return {
        "width": int(w),
        "height": int(h),
        "median_luminance": round(median_lum, 3),
        "contrast": round(contrast, 3),
        "sharpness": round(sharpness, 3),
        "upscaled": round(upscale, 2),
        "inverted": inverted,
    }
