"""FastAPI: proxy + preprocess + re-rank na frente do Claude Vision upstream.

Expõe os mesmos endpoints que o frontend já usa:
    POST /api/identify        multipart com `file`
    POST /api/identify-url    json {"url": "..."}
    POST /api/feedback        json
    GET  /healthz
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import cache as cache_mod
from config import get_settings
from fonts_catalog import lookup
from preprocess import preprocess
from rerank import rerank_candidates
from upstream import UpstreamError, download_image, forward_feedback, identify_image

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("monoid")

app = FastAPI(title="MonoID backend", version="0.2.0")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list or ["*"],
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


class UrlRequest(BaseModel):
    url: str = Field(..., min_length=1)


class FeedbackRequest(BaseModel):
    primary_font: str | None = None
    reason: str | None = None
    details: str | None = None
    suggested_fonts: list[str] = []
    timestamp: str | None = None


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "version": app.version}


@app.post("/api/identify")
async def identify(file: UploadFile = File(...)) -> JSONResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "arquivo vazio")
    return JSONResponse(await _run_pipeline(raw))


@app.post("/api/identify-url")
async def identify_url_endpoint(body: UrlRequest) -> JSONResponse:
    try:
        raw, _mime = await download_image(body.url)
    except UpstreamError as e:
        raise HTTPException(e.status, e.detail) from e
    return JSONResponse(await _run_pipeline(raw))


@app.post("/api/feedback")
async def feedback(body: FeedbackRequest) -> dict:
    payload = body.model_dump()
    # Persiste local sempre (útil quando upstream é offline)
    _append_feedback_log(payload)
    result = await forward_feedback(payload)
    return result


# --------------------------------------------------------------------------- #
# Pipeline core
# --------------------------------------------------------------------------- #

async def _run_pipeline(raw_bytes: bytes) -> dict[str, Any]:
    t0 = time.monotonic()

    # 1. Preprocess
    try:
        pre = preprocess(raw_bytes)
    except Exception as e:
        log.exception("preprocess failed")
        raise HTTPException(400, f"imagem inválida: {e}") from e

    # 2. Cache lookup
    key = cache_mod.compute_key(pre.png_bytes)
    cached = cache_mod.get(key)
    if cached is not None:
        cached = dict(cached)
        cached["cached"] = True
        cached["timing_ms"] = int((time.monotonic() - t0) * 1000)
        return cached

    # 3. Upstream call
    try:
        upstream_resp = await identify_image(pre.png_bytes)
    except UpstreamError as e:
        log.warning("upstream error: %s", e)
        raise HTTPException(e.status if e.status >= 400 else 502, e.detail) from e

    # 4. Re-rank visual (opcional, controlado por env)
    if settings.enable_rerank:
        try:
            final = await rerank_candidates(upstream_resp, pre.gray)
        except Exception as e:
            log.exception("rerank failed — falling back to upstream response")
            final = dict(upstream_resp)
            final["rerank"] = {"applied": False, "reason": f"error: {e}"}
            # Ainda anota `renderable` nos candidatos pra UI
            _annotate_renderable_only(final)
    else:
        final = dict(upstream_resp)
        final["rerank"] = {"applied": False, "reason": "disabled"}
        _annotate_renderable_only(final)

    # 5. Enriquecer com metadados úteis pro frontend
    final["preprocess"] = pre.quality
    final["timing_ms"] = int((time.monotonic() - t0) * 1000)
    final["cached"] = False

    # 6. Salva no cache
    try:
        cache_mod.put(key, final)
    except Exception:
        log.exception("failed to write cache")

    return final


def _annotate_renderable_only(response: dict) -> None:
    for c in [response.get("primary_match") or {}] + (response.get("alternatives") or []):
        if not c:
            continue
        entry = lookup(c.get("name", ""))
        c["renderable"] = bool(entry and entry.renderable)
        c.setdefault("visual_similarity", None)


def _append_feedback_log(payload: dict) -> None:
    path = settings.cache_path / "feedback.log"
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        log.exception("could not append feedback log")
