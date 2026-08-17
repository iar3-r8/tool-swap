# tool_torch — PyTorch fixture for Spike E
# Weights and payload are baked in at build time (§0a of spike-E-implementation.md)

ARG RAY_BASE_TAG
FROM ${RAY_BASE_TAG}

# === Framework deps ===
RUN pip install --no-cache-dir \
    torch==2.8.0+cu129 \
    --extra-index-url https://download.pytorch.org/whl/cu129

# === Shared runtime deps (boto3 removed per §0a: no object storage) ===
RUN pip install --no-cache-dir \
    requests

# === Baked assets (must run before COPY toolkit, so assets are cached) ===
COPY fixtures/make_assets.py /tmp/make_assets.py
ARG WEIGHTS_MB=8
ARG PAYLOAD_MB=64
RUN python /tmp/make_assets.py \
      --weights /opt/spike/weights/ckpt.bin --weights-mb ${WEIGHTS_MB} \
      --payload /opt/spike/data/payload.bin --payload-mb ${PAYLOAD_MB} \
   && rm /tmp/make_assets.py
ENV SPIKE_WEIGHTS_PATH=/opt/spike/weights/ckpt.bin
ENV SPIKE_PAYLOAD_PATH=/opt/spike/data/payload.bin

# === Shared toolkit code ===
COPY toolkit/ /home/ray/toolkit/
COPY apps/ /home/ray/apps/
ENV PYTHONPATH="${PYTHONPATH}:/home/ray"

# === Identity (cannot be faked via runtime_env env_vars) ===
ENV SPIKE_IMAGE_MARKER=tool_torch

WORKDIR /home/ray
