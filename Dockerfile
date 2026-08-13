FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/data

WORKDIR /app
COPY requirements-web.txt requirements-vm.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt -r requirements-vm.txt \
    && python -m playwright install --with-deps chromium

COPY . .
RUN mkdir -p /data && useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /data
USER appuser

EXPOSE 8000
CMD ["sh", "-c", "uvicorn web_app:app --host 0.0.0.0 --port ${PORT:-8000}"]
