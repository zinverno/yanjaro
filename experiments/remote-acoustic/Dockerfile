FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml /app/
COPY remote_acoustic/ /app/remote_acoustic/
RUN pip install --no-cache-dir --disable-pip-version-check '.[serve]'
COPY artifacts/model.json /app/artifacts/model.json
ENV MODEL_PATH=/app/artifacts/model.json
CMD ["sh","-c","exec uvicorn remote_acoustic.service:app --host 0.0.0.0 --port ${PORT:-10000} --no-access-log"]
