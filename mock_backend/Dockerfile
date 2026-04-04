FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 appgroup \
    && useradd --system --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy into mock_backend/ so `from mock_backend.X import ...` resolves correctly
COPY --chown=appuser:appgroup . ./mock_backend/

USER appuser

CMD ["uvicorn", "mock_backend.prometheus_api:app", "--host", "0.0.0.0", "--port", "9090"]
