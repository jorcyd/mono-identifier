# mono-identifier

Identificador de fontes monospace a partir de screenshots de código.

## Arquitetura

```
┌──────────────┐    POST /api/identify     ┌─────────────────────┐   POST /api/identify   ┌──────────────────┐
│   Frontend   │  (imagem + opts)          │  Backend local      │ ─────────────────────▶ │ Upstream Claude  │
│  index.html  │ ────────────────────────▶ │  (FastAPI)          │                        │ Vision (imutável)│
│   app.js     │                           │                     │ ◀───────────────────── └──────────────────┘
└──────────────┘ ◀──────────────────────── │  1. Preprocess      │
                    JSON re-ranqueado      │  2. → upstream      │
                                           │  3. Re-rank visual  │   download TTFs + render
                                           │  4. Recalibra conf. │ ◀──── Google Fonts / OSS
                                           └─────────────────────┘
```

Três camadas:

- **Frontend estático** (HTML/CSS/JS puro): upload, crop, exibição.
- **Backend local (FastAPI)** — adicionado neste repo, faz preprocessamento da
  imagem (upscale adaptativo, CLAHE, unsharp), encaminha pro upstream, e depois
  faz **re-ranking visual**: renderiza cada fonte candidata com `Pillow` e
  compara pixel-a-pixel com o crop original via SSIM + IoU de bordas.
- **Upstream Claude Vision** (fora deste repo, tratado como imutável): faz a
  identificação primária.

O re-ranking aumenta acurácia porque mesmo quando o Claude chuta errado, a
fonte correta costuma estar entre as alternativas — e a comparação pixel-a-pixel
promove ela pro topo.

## Rodando

### Backend

```bash
cd backend
cp .env.example .env
# Edite .env: defina UPSTREAM_BASE_URL (e UPSTREAM_API_KEY se for o caso)

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn main:app --reload --port 8000
```

Ou via Docker:

```bash
cd backend
docker build -t monoid-backend .
docker run --rm -p 8000:8000 --env-file .env -v "$PWD/cache:/app/cache" -v "$PWD/fonts_cache:/app/fonts_cache" monoid-backend
```

### Frontend

Serve os estáticos em outra porta apontando pro backend:

```bash
# Na raiz do repo
python -m http.server 5500
```

Abre `http://localhost:5500`. Por padrão o frontend chama `http://localhost:8000`.
Para apontar pra outro endpoint, inclua no `index.html`:

```html
<meta name="monoid-api" content="https://meu-backend.example.com">
```

Ou, em runtime: `window.MONOID_API = "https://...";` antes de carregar `app.js`.

## Avaliando a acurácia

Com algumas imagens rotuladas em `backend/eval/dataset/` e `cases.json`
preenchido, rode:

```bash
cd backend
python -m eval.run_eval                # com re-rank
python -m eval.run_eval --no-rerank    # baseline
```

Ele reporta top-1/top-3 accuracy, confusões mais frequentes e tempo por caso.
Detalhes em `backend/eval/README.md`.

## O que o re-ranking considera

Para cada candidato que o upstream retorna:

1. Tenta mapear o nome pra uma `FontEntry` do catálogo (`backend/fonts_catalog.py`).
   Fontes pagas / não-Google (Operator Mono, MonoLisa, SF Mono, ...) ficam
   marcadas como `renderable=False` e **não** entram no re-rank — o frontend
   mostra "não verificável visualmente".
2. Baixa o TTF (Google Fonts via CSS API, ou URL direta do GitHub) com cache local.
3. Renderiza o `extracted_code` devolvido pelo upstream em preto sobre branco.
4. Alinha com o crop original via template matching multi-escala (OpenCV).
5. Calcula similaridade = `0.6 * SSIM + 0.4 * IoU de bordas` na janela alinhada.
6. Re-ordena; se o melhor visual supera o primary atual por ≥ 8 pontos, promove.
7. Mistura o score visual na confiança final: `0.7 * visual + 0.3 * upstream`.

## Limitações conhecidas

- Fontes pagas: sem TTF público, não dá para re-ranquear — caímos de volta na
  ordem do upstream e expomos o flag.
- OCR do upstream: se `extracted_code` vem errado, a renderização também erra.
- Custo: ~1-3s extra por análise na primeira vez; respostas idênticas são
  servidas do cache em < 200ms (hash SHA256 da imagem preprocessada).
