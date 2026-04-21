"""Catálogo de fontes monospace conhecidas.

Cada entrada diz se a fonte é renderizável (Google Fonts, open source com URL
pública) ou não (fontes pagas, distribuição restrita). Fontes não renderizáveis
não participam do re-ranking visual — mantemos a ordem que o upstream deu e
marcamos como "não verificada visualmente".

Para fontes Google Fonts a gente resolve a URL do TTF consultando a API
`https://fonts.googleapis.com/css2?family=X` em runtime, então aqui só precisamos
do `family` normalizado. Para fontes hospedadas em outro lugar (ex: Cascadia
Code no GitHub), damos a URL direta do TTF.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FontEntry:
    canonical: str
    source: str                 # "google" | "url" | "unavailable"
    ttf_url: Optional[str] = None  # preenchido para source="url"
    is_free: bool = True
    homepage: Optional[str] = None
    aliases: tuple[str, ...] = ()

    @property
    def renderable(self) -> bool:
        return self.source != "unavailable"


# --------------------------------------------------------------------------- #
# Catálogo principal.
# Mantenha ordenado alfabeticamente para facilitar revisão.
# --------------------------------------------------------------------------- #
_CATALOG: list[FontEntry] = [
    # === Google Fonts (renderizáveis direto) ===
    FontEntry("Anonymous Pro", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Anonymous+Pro"),
    FontEntry("B612 Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/B612+Mono"),
    FontEntry("Courier Prime", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Courier+Prime"),
    FontEntry("Cousine", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Cousine"),
    FontEntry("Cutive Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Cutive+Mono"),
    FontEntry("DM Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/DM+Mono"),
    FontEntry("Fira Code", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Fira+Code",
              aliases=("FiraCode",)),
    FontEntry("Fira Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Fira+Mono"),
    FontEntry("IBM Plex Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/IBM+Plex+Mono",
              aliases=("Plex Mono",)),
    FontEntry("Inconsolata", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Inconsolata"),
    FontEntry("JetBrains Mono", "google", is_free=True,
              homepage="https://www.jetbrains.com/lp/mono/",
              aliases=("JetBrainsMono", "Jet Brains Mono")),
    FontEntry("Major Mono Display", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Major+Mono+Display"),
    FontEntry("Nanum Gothic Coding", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Nanum+Gothic+Coding"),
    FontEntry("Noto Sans Mono", "google", is_free=True,
              homepage="https://fonts.google.com/noto/specimen/Noto+Sans+Mono"),
    FontEntry("Overpass Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Overpass+Mono"),
    FontEntry("PT Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/PT+Mono"),
    FontEntry("Red Hat Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Red+Hat+Mono"),
    FontEntry("Roboto Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Roboto+Mono"),
    FontEntry("Share Tech Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Share+Tech+Mono"),
    FontEntry("Source Code Pro", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Source+Code+Pro",
              aliases=("SourceCodePro",)),
    FontEntry("Space Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Space+Mono"),
    FontEntry("Syne Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Syne+Mono"),
    FontEntry("Ubuntu Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Ubuntu+Mono"),
    FontEntry("VT323", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/VT323"),
    FontEntry("Xanh Mono", "google", is_free=True,
              homepage="https://fonts.google.com/specimen/Xanh+Mono"),

    # === Open-source hospedadas em outro lugar ===
    FontEntry(
        "Cascadia Code", "url",
        ttf_url="https://github.com/microsoft/cascadia-code/raw/main/sources/CascadiaCode-Regular.otf",
        is_free=True,
        homepage="https://github.com/microsoft/cascadia-code",
        aliases=("Cascadia Mono",),
    ),
    FontEntry(
        "Hack", "url",
        ttf_url="https://github.com/source-foundry/Hack/raw/master/build/ttf/Hack-Regular.ttf",
        is_free=True,
        homepage="https://sourcefoundry.org/hack/",
    ),
    FontEntry(
        "Iosevka", "url",
        ttf_url="https://github.com/be5invis/Iosevka/releases/latest/download/PkgTTF-Iosevka.zip",
        # Nota: é um zip. Re-rank deve tratar como não-renderizável se download falha.
        is_free=True,
        homepage="https://typeof.net/Iosevka/",
    ),
    FontEntry(
        "Monaspace Neon", "url",
        ttf_url="https://github.com/githubnext/monaspace/raw/main/fonts/otf/MonaspaceNeon-Regular.otf",
        is_free=True,
        homepage="https://monaspace.githubnext.com/",
        aliases=("Monaspace",),
    ),
    FontEntry(
        "Monaspace Argon", "url",
        ttf_url="https://github.com/githubnext/monaspace/raw/main/fonts/otf/MonaspaceArgon-Regular.otf",
        is_free=True,
        homepage="https://monaspace.githubnext.com/",
    ),
    FontEntry(
        "Monaspace Xenon", "url",
        ttf_url="https://github.com/githubnext/monaspace/raw/main/fonts/otf/MonaspaceXenon-Regular.otf",
        is_free=True,
        homepage="https://monaspace.githubnext.com/",
    ),
    FontEntry(
        "Monaspace Radon", "url",
        ttf_url="https://github.com/githubnext/monaspace/raw/main/fonts/otf/MonaspaceRadon-Regular.otf",
        is_free=True,
        homepage="https://monaspace.githubnext.com/",
    ),
    FontEntry(
        "Monaspace Krypton", "url",
        ttf_url="https://github.com/githubnext/monaspace/raw/main/fonts/otf/MonaspaceKrypton-Regular.otf",
        is_free=True,
        homepage="https://monaspace.githubnext.com/",
    ),
    FontEntry(
        "Geist Mono", "url",
        ttf_url="https://github.com/vercel/geist-font/raw/main/packages/next/dist/fonts/geist-mono/GeistMono-Regular.otf",
        is_free=True,
        homepage="https://vercel.com/font",
    ),
    FontEntry(
        "Departure Mono", "url",
        ttf_url="https://departuremono.com/assets/DepartureMono-Regular.otf",
        is_free=True,
        homepage="https://departuremono.com/",
    ),
    FontEntry(
        "Commit Mono", "url",
        ttf_url="https://github.com/eigilnikolajsen/commit-mono/releases/latest/download/CommitMono.zip",
        is_free=True,
        homepage="https://commitmono.com/",
    ),
    FontEntry(
        "Maple Mono", "url",
        ttf_url="https://github.com/subframe7536/maple-font/raw/variable/woff2/MapleMono-Regular.ttf",
        is_free=True,
        homepage="https://font.subf.dev/",
    ),

    # === Pagas / distribuição restrita — não re-ranqueamos visualmente ===
    FontEntry("Berkeley Mono", "unavailable", is_free=False,
              homepage="https://berkeleygraphics.com/typefaces/berkeley-mono/"),
    FontEntry("Dank Mono", "unavailable", is_free=False,
              homepage="https://dank.sh/"),
    FontEntry("Monolisa", "unavailable", is_free=False,
              homepage="https://www.monolisa.dev/",
              aliases=("Mono Lisa", "MonoLisa")),
    FontEntry("Operator Mono", "unavailable", is_free=False,
              homepage="https://www.typography.com/fonts/operator/overview"),
    FontEntry("Pragmata Pro", "unavailable", is_free=False,
              homepage="https://fsd.it/shop/fonts/pragmatapro/",
              aliases=("PragmataPro",)),
    FontEntry("SF Mono", "unavailable", is_free=False,
              homepage="https://developer.apple.com/fonts/",
              aliases=("San Francisco Mono",)),
    FontEntry("Input Mono", "unavailable", is_free=False,
              homepage="https://input.djr.com/"),
    FontEntry("Consolas", "unavailable", is_free=False,
              homepage="https://docs.microsoft.com/en-us/typography/font-list/consolas"),
    FontEntry("Menlo", "unavailable", is_free=False,
              homepage="https://developer.apple.com/fonts/"),
    FontEntry("Monaco", "unavailable", is_free=False,
              homepage="https://developer.apple.com/fonts/"),
    FontEntry("Courier New", "unavailable", is_free=False,
              homepage="https://learn.microsoft.com/en-us/typography/font-list/courier-new"),
    FontEntry("Courier", "unavailable", is_free=False,
              homepage=None),
    FontEntry("Lucida Console", "unavailable", is_free=False,
              homepage=None),
]


# Índice para lookup rápido por nome/alias normalizado
def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


_INDEX: dict[str, FontEntry] = {}
for _entry in _CATALOG:
    _INDEX[_norm(_entry.canonical)] = _entry
    for alias in _entry.aliases:
        _INDEX[_norm(alias)] = _entry


def lookup(name: str) -> Optional[FontEntry]:
    """Retorna a entrada canônica para um nome (com tolerância a aliases)."""
    if not name:
        return None
    key = _norm(name)
    if key in _INDEX:
        return _INDEX[key]
    # fallback: match parcial (ex: "JetBrains Mono Regular" → contém "jetbrainsmono")
    for idx_key, entry in _INDEX.items():
        if idx_key in key or key in idx_key:
            return entry
    return None


def all_entries() -> list[FontEntry]:
    return list(_CATALOG)
