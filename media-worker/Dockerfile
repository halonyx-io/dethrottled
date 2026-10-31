FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.121.3 uvicorn==0.38.0 faster-whisper==1.2.1 \
    && useradd --create-home --uid 10003 mediaworker \
    && mkdir /models && chown mediaworker:mediaworker /models
COPY service.py ./
USER mediaworker
ENV WHISPER_MODEL=small
EXPOSE 19889
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "19889"]
