FROM node:20-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    NODE_ENV=production \
    NPM_CONFIG_LEGACY_PEER_DEPS=true \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false

# Dependencias do Python/PostgreSQL e ferramentas exigidas pelas dependencias
# do Baileys no npm (incluindo pacotes obtidos via Git durante o build).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        openssl \
        git \
        python3 \
        python3-venv \
        python3-pip \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python3 -m venv /opt/venv

COPY requirements.txt package*.json ./
RUN pip install --no-cache-dir -r requirements.txt \
    && npm install --omit=dev --legacy-peer-deps --no-audit --no-fund

COPY . .
RUN chmod +x start.sh

CMD ["./start.sh"]
