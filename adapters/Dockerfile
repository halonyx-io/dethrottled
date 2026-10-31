FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir mcp==1.28.1 httpx==0.28.1 uvicorn==0.38.0 fastapi==0.121.3 \
    && useradd --create-home --uid 10004 adapter \
    && mkdir /state && chown adapter:adapter /state
COPY src/dethrottled/access.py ./dethrottled_access.py
COPY src/dethrottled/workflow.py ./dethrottled_workflow.py
COPY adapters/mcp_server.py ./server.py
COPY adapters/rest_gateway.py ./public_gateway.py
USER adapter
ENV DETHROTTLED_ADMISSION_DB=/state/admission.sqlite \
    DETHROTTLED_TOKEN_REGISTRY=/run/secrets/tokens.json
EXPOSE 18184 18186
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "18184"]
