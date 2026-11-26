FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    TZ=Asia/Hong_Kong

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libgdk-pixbuf-2.0-0 \
        libcairo2 \
        libpangocairo-1.0-0 \
        shared-mime-info \
        fonts-noto-cjk \
        tzdata \
    && ln -snf /usr/share/zoneinfo/Asia/Hong_Kong /etc/localtime \
    && echo Asia/Hong_Kong > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

RUN mkdir -p /data/uploads
VOLUME ["/data"]
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
