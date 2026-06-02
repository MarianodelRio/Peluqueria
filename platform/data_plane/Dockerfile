FROM python:3.14-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
COPY uv.lock .
RUN uv sync --frozen --no-dev
COPY . .
ENV PYTHONPATH=/app
ENV TENANT_CONFIG_PATH=/config/tenant.yaml
VOLUME /data
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "data_plane.main:app", "--host", "0.0.0.0", "--port", "8000"]
