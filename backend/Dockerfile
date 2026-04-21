FROM python:3.11-slim

# Dependências de sistema do OpenCV (opencv-python-headless já vem sem GUI, mas
# precisa de libgomp e libGL mínimos em algumas distros).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Diretórios de cache são volumes úteis em produção
RUN mkdir -p /app/cache /app/fonts_cache

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
