# Gateway + frontend in one image, for a Runpod CPU Pod. Build from the repo root:
#   docker build --platform linux/amd64 -f gateway/Dockerfile -t <you>/river-outlook-gateway:0.1 .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

COPY gateway/requirements.txt gateway/requirements.txt
RUN pip install --no-cache-dir -r gateway/requirements.txt

COPY gateway/app gateway/app
COPY frontend frontend

WORKDIR /srv/gateway
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
