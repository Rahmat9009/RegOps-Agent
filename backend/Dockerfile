FROM python:3.12.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

RUN addgroup --system regops && adduser --system --ingroup regops regops

COPY pyproject.toml README.md requirements-runtime.lock ./
COPY src ./src

RUN pip install --no-cache-dir -r requirements-runtime.lock \
    && pip install --no-cache-dir --no-deps .

USER regops
EXPOSE 8080

CMD ["sh", "-c", "uvicorn regops_api.main:app --host 0.0.0.0 --port ${PORT}"]
