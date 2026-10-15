# Runpod Serverless worker. Build for x86 GPUs, also from an Apple Silicon Mac:
#   docker build --platform linux/amd64 -t <you>/river-outlook-worker:0.1 worker/
FROM pytorch/pytorch:2.13.0-cuda12.6-cudnn9-runtime

WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/models

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the weights into the image so a cold worker does not download them.
RUN python -c "from chronos import Chronos2Pipeline; Chronos2Pipeline.from_pretrained('amazon/chronos-2', device_map='cpu')"

COPY forecast.py handler.py ./
CMD ["python", "-u", "handler.py"]
