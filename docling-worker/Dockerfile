FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir docling==2.145.0 fastapi==0.121.3 uvicorn==0.38.0 \
    && useradd --create-home --uid 10004 docworker && mkdir /models && chown docworker:docworker /models
COPY service.py convert.py ./
USER docworker
ENV HF_HOME=/models OMP_NUM_THREADS=4
EXPOSE 19891
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "19891"]
