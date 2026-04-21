# Avaliação de acurácia

Harness para medir acurácia top-1/top-3 antes e depois do re-ranking visual.

## Dataset

Coloque PNGs/JPEGs rotulados em `dataset/` e edite `cases.json` com o nome
canônico da fonte verdadeira:

```json
[
  {"file": "screenshot1.png", "true_font": "JetBrains Mono", "notes": "VS Code dark theme"},
  {"file": "screenshot2.png", "true_font": "Fira Code", "notes": "ligaduras visíveis"}
]
```

As entradas que permanecem com `"__placeholder__": true` são ignoradas até que
o arquivo real exista em `dataset/`.

## Rodando

```bash
cd backend
# Certifique-se que o .env aponta para um upstream válido.
python -m eval.run_eval
```

Comparar com baseline (sem re-rank):

```bash
python -m eval.run_eval --no-rerank
```

Resultado fica em `results_<timestamp>.json` e um resumo é impresso no stdout.

## Meta

Com ~30 casos, esperamos top-1 subir em >= 15 pontos percentuais versus o
baseline do upstream puro, e top-3 ficar acima de 90%.
