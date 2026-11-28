# Template (owner: Claude 3). Build from the repository root:
#   docker build -f infra/ai-gateway/Dockerfile -t glassflow-judge-gateway .
# Provider keys and the tokens file are injected by the host's secret store, never baked in.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv==0.8.17
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend ./backend
COPY infra/ai-gateway ./infra/ai-gateway
RUN uv sync --locked --no-dev --group intelligence
ENV PYTHONPATH=/app/infra/ai-gateway
EXPOSE 8080
USER nobody
CMD ["uv", "run", "--no-sync", "python", "-m", "judge_gateway", "serve", "--host", "0.0.0.0", "--port", "8080"]
