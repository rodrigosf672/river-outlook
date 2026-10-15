# Runpod Serverless worker. Build for x86 GPUs, also from an Apple Silicon Mac:
#   docker build --platform linux/amd64 -t <you>/river-outlook-worker:0.1 worker/
# Official Runpod base: torch/CUDA match the hosts, and its layers are often
# already cached there, which shortens cold starts.
FROM runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404

WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/models

# A venv that still sees the base image's torch/CUDA. Ubuntu 24.04 blocks pip on
# system Python (PEP 668) and owns packages pip cannot upgrade (cryptography);
# in the venv, newer versions shadow them instead of replacing them.
RUN python3 -m venv --system-site-packages /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -c "import torch, chronos; print('torch', torch.__version__)"

# Bake the weights into the image so a cold worker does not download them.
RUN python -c "from chronos import Chronos2Pipeline; Chronos2Pipeline.from_pretrained('amazon/chronos-2', device_map='cpu')"

COPY forecast.py handler.py ./
CMD ["python", "-u", "handler.py"]
