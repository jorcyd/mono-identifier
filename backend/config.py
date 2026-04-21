"""Configuração do backend carregada de variáveis de ambiente."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    upstream_base_url: str = "https://upstream.example.com"
    upstream_api_key: str = ""
    upstream_timeout: float = 60.0

    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500,http://localhost:8000"

    enable_rerank: bool = True
    cache_ttl_seconds: int = 604800

    cache_dir: str = "cache"
    fonts_cache_dir: str = "fonts_cache"

    target_long_edge: int = 1600
    min_long_edge_for_upscale: int = 1200

    @property
    def cache_path(self) -> Path:
        p = BACKEND_DIR / self.cache_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def fonts_cache_path(self) -> Path:
        p = BACKEND_DIR / self.fonts_cache_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
