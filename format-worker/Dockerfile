FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless curl && rm -rf /var/lib/apt/lists/*
RUN curl -fSL https://repo.maven.apache.org/maven2/org/apache/tika/tika-app/3.3.3/tika-app-3.3.3.jar -o /opt/tika.jar && python -c "import hashlib,pathlib; assert hashlib.sha512(pathlib.Path('/opt/tika.jar').read_bytes()).hexdigest()=='3c6e62e864e32af234832ec6d928bbc58692d3ddd60564cd8c80dee7e161653d6efcba373b6cc9468c778010bea92bdee5ca75ab24f01923480bec1b29b573fd'"
RUN pip install --no-cache-dir fastapi==0.121.3 uvicorn==0.38.0 && useradd --create-home --uid 10005 formatworker
COPY format-worker/service.py ./
COPY format-worker/tika_convert.py ./convert.py
COPY workers/runtime.py ./
USER formatworker
ENV FORMAT_ENGINE=apache-tika FORMAT_VERSION=3.3.3
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:19892/health',timeout=3)"
EXPOSE 19892
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "19892"]
