# Imagem única usada pelos 3 serviços do Railway (web, worker, beat) —
# o que muda entre eles é só o start command, configurado no dashboard
# de cada serviço, não a imagem.

FROM python:3.12-slim

WORKDIR /app

# psycopg[binary] já traz o binário compilado, não precisa de libpq-dev.
# build-essential fica só pra dependências que compilam C na instalação
# (mais seguro manter do que descobrir na hora que falta em produção).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway injeta $PORT dinamicamente — nunca fixar 8000 direto no CMD.
# Este é o comando do serviço "web". Os serviços "worker" e "beat" sobrescrevem
# isso no dashboard do Railway com os comandos do Celery (ver README).
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
