# Runpod Serverless worker. Build for x86 GPUs, also from an Apple Silicon Mac:
#   docker build --platform linux/amd64 -t <you>/river-outlook-worker:0.1 worker/
# Official Runpod base: torch/CUDA match the hosts, and its layers are often
# already cached there, which shortens cold starts.
FROM runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404

WORKDIR /app
# Ubuntu 24.04 marks system Python as externally managed (PEP 668); this is a
# single-purpose container, so installing into it is fine.
ENV PYTHONUNBUFFERED=1 HF_HOME=/models PIP_BREAK_SYSTEM_PACKAGES=1

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Bake the weights into the image so a cold worker does not download them.
RUN python3 -c "from chronos import Chronos2Pipeline; Chronos2Pipeline.from_pretrained('amazon/chronos-2', device_map='cpu')"

COPY forecast.py handler.py ./
CMD ["python3", "-u", "handler.py"]
