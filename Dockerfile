# Multi-arch by construction: python:3.12-slim publishes both linux/amd64 and
# linux/arm64, and every dependency below is either pure Python or ships wheels
# for both. Nothing here is compiled from source at build time, which is why
# this image builds on a laptop and on a single-board ARM machine alike.
FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

# OCR and legacy Office converters are local command-line tools. English,
# Malay and Chinese OCR data ship in the image; select a known language for
# better results rather than indiscriminately combining language packs.
#
# --no-install-recommends because the recommended set drags in a large chunk of
# X11 for a command-line binary that never opens a window.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-osd \
        tesseract-ocr-msa tesseract-ocr-chi-sim tesseract-ocr-chi-tra \
        antiword catdoc \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, in their own layer, so editing the source does not
# reinstall onnxruntime every time.
COPY requirements/docker-py312.txt ./requirements/docker-py312.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements/docker-py312.txt

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
ARG E5_REVISION=614241f622f53c4eeff9890bdc4f31cfecc418b3
ARG MINILM_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41
ENV DETHROTTLED_MODEL_DIR=/opt/dethrottled/models \
    PYTHONUNBUFFERED=1
RUN if [ "$WITH_MODELS" = "1" ]; then \
        mkdir -p /opt/dethrottled/models/emb-minilm \
     && base=https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/$MINILM_REVISION \
     && curl -fsSL -o /opt/dethrottled/models/emb-minilm/model.onnx "$base/onnx/model.onnx" \
     && curl -fsSL -o /opt/dethrottled/models/emb-minilm/tokenizer.json "$base/tokenizer.json"; \
    fi

# Separate multilingual index; the model revision is part of stored vector IDs.
ENV DETHROTTLED_E5_REVISION=$E5_REVISION
RUN if [ "$WITH_MODELS" = "1" ]; then \
        mkdir -p /opt/dethrottled/models/emb-e5 \
     && base=https://huggingface.co/intfloat/multilingual-e5-small/resolve/$E5_REVISION \
     && curl -fsSL -o /opt/dethrottled/models/emb-e5/model.onnx "$base/onnx/model.onnx" \
     && curl -fsSL -o /opt/dethrottled/models/emb-e5/tokenizer.json "$base/tokenizer.json"; \
    fi

# Source-only updates reuse dependency and model layers. Freeze the deployed
# runtime independently of Python source-install compatibility ranges.
COPY Dockerfile pyproject.toml setup.py MANIFEST.in README.md AGENTS.md SKILL-dethrottled.md LICENSE .dockerignore docker-compose.yml docker-compose.agents.yml docker-compose.gpu.yml docker-compose.pdf-worker.yml ./
COPY docker/ ./docker/
COPY browser-search/ ./browser-search/
COPY experiments/dnb/*.py experiments/dnb/start.sh ./experiments/dnb/
COPY workers/ ./workers/
COPY format-worker/ ./format-worker/
COPY media-worker/ ./media-worker/
COPY docling-worker/ ./docling-worker/
COPY docs/ ./docs/
COPY evaluations/ ./evaluations/
COPY adapters/ ./adapters/
COPY scripts/ ./scripts/
COPY src/ ./src/
COPY scripts/verify_image.py ./verify_image.py
RUN pip install --no-cache-dir --no-deps .

# Unprivileged. The service fetches URLs chosen by whoever can reach it, which
# is a good enough reason on its own not to run it as root.
RUN useradd --create-home --uid 10001 dethrottled \
    && mkdir -p /data \
    && chown dethrottled:dethrottled /data
# Keep documentation changes out of the dependency and model-download layers.
COPY docs/ ./docs/
COPY evaluations/ ./evaluations/
COPY adapters/ ./adapters/
COPY scripts/ ./scripts/
COPY README.md AGENTS.md SKILL-dethrottled.md LICENSE ./
RUN chmod -R a+rX /app/docs /app/evaluations
RUN mkdir -p /filters /trust /models/rerank-ettin-68m \
    && chown 10001:10001 /filters /trust /models/rerank-ettin-68m \
    && chmod 2770 /filters /trust
USER dethrottled

ENV DETHROTTLED_DATA_DIR=/data \
    DETHROTTLED_PORT=8787 \
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
