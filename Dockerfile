# Multi-arch by construction: python:3.12-slim publishes both linux/amd64 and
# linux/arm64, and every dependency below is either pure Python or ships wheels
# for both. Nothing here is compiled from source at build time, which is why
# this image builds on a laptop and on a single-board ARM machine alike.
FROM python:3.12-slim

# tesseract is the only system binary, and only the OCR path uses it. eng and
# osd live in the system tessdata directory; optional extra language packs
# can be downloaded separately -- see scripts/fetch-models.sh.
#
# --no-install-recommends because the recommended set drags in a large chunk of
# X11 for a command-line binary that never opens a window.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-osd \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, in their own layer, so editing the source does not
# reinstall onnxruntime every time.
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY scripts/verify_image.py ./verify_image.py
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[all]"

# The models, baked in.
#
# The 87MB embedding model makes corpus search available in the image: the
# corpus is an advertised capability, and without weights it cannot answer
# semantic queries. An image
# that needs a second, undocumented download is not self-contained.
#
# They live in /opt, NOT in /data. /data is a volume, and anything written
# there during the build is shadowed the moment a volume is mounted over it --
# which would put the models back to being absent exactly when someone follows
# the documented setup.
#
# Build with --build-arg WITH_MODELS=0 for a smaller image without them.
ARG WITH_MODELS=1
ARG MINILM_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41
ENV DETHROTTLED_MODEL_DIR=/opt/dethrottled/models \
    PYTHONUNBUFFERED=1
RUN if [ "$WITH_MODELS" = "1" ]; then \
        mkdir -p /opt/dethrottled/models/emb-minilm \
     && base=https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/$MINILM_REVISION \
     && curl -fsSL -o /opt/dethrottled/models/emb-minilm/model.onnx "$base/onnx/model.onnx" \
     && curl -fsSL -o /opt/dethrottled/models/emb-minilm/tokenizer.json "$base/tokenizer.json"; \
    fi

# Unprivileged. The service fetches URLs chosen by whoever can reach it, which
# is a good enough reason on its own not to run it as root.
RUN useradd --create-home --uid 10001 dethrottled \
    && mkdir -p /data \
    && chown dethrottled:dethrottled /data
# Keep documentation changes out of the dependency and model-download layers.
COPY docs/ ./docs/
USER dethrottled

ENV DETHROTTLED_DATA_DIR=/data \
    DETHROTTLED_PORT=8787 \
    # Inside compose the renderer is a sibling container, so the external
    # reader is not needed and is off. Override it if you want it anyway.
    DETHROTTLED_ENABLE_JINA=0 \
    PYTHONUNBUFFERED=1

EXPOSE 8787
VOLUME ["/data"]

# Asks the service to prove it can do its job, not merely that it is listening.
# /health is the cheap liveness answer; see /v2/status for the honest one.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8787/health || exit 1

# 0.0.0.0 inside the container only. What the outside world can reach is
# decided by the port mapping in compose, which binds to loopback.
CMD ["dethrottled", "--host", "0.0.0.0", "--port", "8787"]
