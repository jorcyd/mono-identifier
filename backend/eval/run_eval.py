"""Harness de avaliação.

Roda o pipeline completo (preprocess + upstream + rerank) em cada caso do
dataset e reporta top-1/top-3 accuracy, matriz de confusão básica e tempo médio.

Uso:
    cd backend
    python -m eval.run_eval
    python -m eval.run_eval --no-rerank  # baseline só com upstream
    python -m eval.run_eval --limit 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

# Permite rodar como `python -m eval.run_eval` ou `python eval/run_eval.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EVAL_DIR = Path(__file__).resolve().parent
DATASET_DIR = EVAL_DIR / "dataset"


def _bootstrap_settings(no_rerank: bool) -> None:
    """Precisa ocorrer ANTES de importar main, porque main captura settings no
    nível do módulo.
    """
    if no_rerank:
        os.environ["ENABLE_RERANK"] = "false"


def load_cases() -> list[dict]:
    with (EVAL_DIR / "cases.json").open("r", encoding="utf-8") as f:
        cases = json.load(f)
    return [c for c in cases if not c.get("__placeholder__") or (DATASET_DIR / c["file"]).exists()]


def _norm(name: str) -> str:
    from fonts_catalog import lookup
    entry = lookup(name)
    return (entry.canonical if entry else name or "").lower()


async def run_one(path: Path, true_font: str) -> dict:
    from main import _run_pipeline
    raw = path.read_bytes()
    t0 = time.monotonic()
    try:
        resp = await _run_pipeline(raw)
    except Exception as e:
        return {"file": path.name, "error": str(e), "took_ms": 0}
    took = int((time.monotonic() - t0) * 1000)

    primary = resp.get("primary_match") or {}
    alternatives = resp.get("alternatives") or []
    predicted = [primary.get("name")] + [a.get("name") for a in alternatives]
    predicted = [p for p in predicted if p]

    true_norm = _norm(true_font)
    ranks = [i for i, name in enumerate(predicted) if _norm(name) == true_norm]
    rank = ranks[0] if ranks else None

    return {
        "file": path.name,
        "true_font": true_font,
        "predicted_top1": predicted[0] if predicted else None,
        "predicted_top3": predicted[:3],
        "rank": rank,  # None = não apareceu
        "visual_similarity_top1": primary.get("visual_similarity"),
        "rerank_applied": (resp.get("rerank") or {}).get("applied", False),
        "rerank_promoted": (resp.get("rerank") or {}).get("promoted", False),
        "took_ms": took,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Roda só os primeiros N casos")
    parser.add_argument("--no-rerank", action="store_true", help="Desabilita re-rank (baseline)")
    args = parser.parse_args()

    _bootstrap_settings(no_rerank=args.no_rerank)

    cases = load_cases()
    if args.limit > 0:
        cases = cases[: args.limit]

    if not cases:
        print("Nenhum caso encontrado. Coloque PNGs rotulados em backend/eval/dataset/")
        print("e atualize cases.json removendo as entradas '__placeholder__: true'.")
        return 1

    print(f"Avaliando {len(cases)} casos (rerank {'OFF' if args.no_rerank else 'ON'})...\n")

    results = []
    for case in cases:
        path = DATASET_DIR / case["file"]
        if not path.exists():
            print(f"  · SKIP {case['file']} (não existe em dataset/)")
            continue
        r = await run_one(path, case["true_font"])
        results.append(r)
        rank_str = f"rank={r['rank']}" if r.get("rank") is not None else "rank=∞"
        vs = r.get("visual_similarity_top1")
        vs_str = f" vs={vs:.2f}" if isinstance(vs, (int, float)) else ""
        print(
            f"  · {r['file']:<40s} "
            f"esperado={r['true_font']:<25s} "
            f"top1={(r.get('predicted_top1') or '—'):<25s} "
            f"{rank_str}{vs_str} "
            f"({r['took_ms']}ms)"
        )

    n = len(results)
    top1 = sum(1 for r in results if r.get("rank") == 0)
    top3 = sum(1 for r in results if r.get("rank") is not None and r["rank"] < 3)
    promoted = sum(1 for r in results if r.get("rerank_promoted"))
    avg_time = (sum(r["took_ms"] for r in results) / n) if n else 0

    print("\n=== Resumo ===")
    print(f"  Top-1 accuracy : {top1}/{n}  ({top1/n*100:.1f}% )" if n else "  n/a")
    print(f"  Top-3 accuracy : {top3}/{n}  ({top3/n*100:.1f}% )" if n else "")
    print(f"  Promovidos pelo re-rank : {promoted}")
    print(f"  Tempo médio    : {avg_time:.0f}ms")

    # Matriz de confusão simples (top-1 wrong cases)
    confusions = Counter()
    for r in results:
        if r.get("rank") != 0 and r.get("predicted_top1") and r.get("true_font"):
            confusions[(r["true_font"], r["predicted_top1"])] += 1
    if confusions:
        print("\n  Confusões mais frequentes (top-1 errado):")
        for (true_f, pred_f), count in confusions.most_common(10):
            print(f"    {true_f:<25s} → {pred_f:<25s}  ({count}x)")

    # Salva JSON com os detalhes
    out = EVAL_DIR / f"results_{int(time.time())}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Detalhes salvos em: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
