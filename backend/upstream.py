"""Cliente HTTP para o backend upstream (Claude Vision, imutável)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import get_settings

log = logging.getLogger(__name__)


class UpstreamError(Exception):
    """Erro ao chamar o upstream. Contém status e detalhe do erro."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"upstream returned {status}: {detail}")
        self.status = status
        self.detail = detail


def _auth_headers() -> dict[str, str]:
    key = get_settings().upstream_api_key
    return {"Authorization": f"Bearer {key}"} if key else {}


async def identify_image(image_bytes: bytes, filename: str = "image.png", mime: str = "image/png") -> dict[str, Any]:
    """POST /api/identify no upstream, com a imagem já preprocessada."""
    settings = get_settings()
    url = f"{settings.upstream_base_url.rstrip('/')}/api/identify"

    async with httpx.AsyncClient(timeout=settings.upstream_timeout) as client:
        files = {"file": (filename, image_bytes, mime)}
        resp = await client.post(url, files=files, headers=_auth_headers())

    if resp.status_code >= 400:
        detail = _extract_detail(resp)
        raise UpstreamError(resp.status_code, detail)

    return resp.json()


async def identify_url(image_url: str) -> dict[str, Any]:
    """POST /api/identify-url no upstream. Usado quando o usuário cola URL.

    Nota: nesse caminho o upstream baixa a imagem, então não conseguimos preprocessar.
    Para máxima qualidade o ideal é baixar aqui e mandar como arquivo — ver main.py.
    """
    settings = get_settings()
    url = f"{settings.upstream_base_url.rstrip('/')}/api/identify-url"

    async with httpx.AsyncClient(timeout=settings.upstream_timeout) as client:
        resp = await client.post(url, json={"url": image_url}, headers=_auth_headers())

    if resp.status_code >= 400:
        detail = _extract_detail(resp)
        raise UpstreamError(resp.status_code, detail)

    return resp.json()


async def forward_feedback(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /api/feedback no upstream. Se o upstream falhar, logamos local."""
    settings = get_settings()
    url = f"{settings.upstream_base_url.rstrip('/')}/api/feedback"

    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout) as client:
            resp = await client.post(url, json=payload, headers=_auth_headers())
        if resp.status_code < 400:
            return resp.json() if resp.content else {"ok": True}
        log.warning("upstream feedback returned %s: %s", resp.status_code, _extract_detail(resp))
    except httpx.HTTPError as e:
        log.warning("upstream feedback network error: %s", e)

    # Fallback: armazena local para não perder o sinal.
    return {"ok": True, "stored_locally": True}


async def download_image(url: str) -> tuple[bytes, str]:
    """Baixa imagem de URL arbitrária. Retorna (bytes, mime)."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.upstream_timeout, follow_redirects=True) as client:
        resp = await client.get(url)
    if resp.status_code >= 400:
        raise UpstreamError(resp.status_code, f"falha ao baixar imagem: {resp.reason_phrase}")
    mime = resp.headers.get("content-type", "image/png").split(";")[0].strip()
    if not mime.startswith("image/"):
        raise UpstreamError(400, f"URL não é uma imagem (content-type={mime})")
    return resp.content, mime


def _extract_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return data.get("detail") or data.get("error") or resp.text
    except Exception:
        return resp.text or resp.reason_phrase
