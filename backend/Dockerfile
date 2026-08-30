FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl is used by the compose healthcheck; ca-certificates by the Claude Agent SDK.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
# Shell form so ${PORT} expands: Render and most PaaS hosts assign the port and
# health-check it, and a hardcoded one never comes up. Defaults to 8000 so
# docker compose is unchanged. RELOAD is opt-in and must stay off in production.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} ${RELOAD:+--reload}
