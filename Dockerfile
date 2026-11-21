FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    DATA_DIR=/data

WORKDIR /app

COPY app ./app

RUN mkdir -p /data/photos && chmod -R 777 /data

EXPOSE 8080

VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)" || exit 1

CMD ["python3", "-m", "app.server"]
