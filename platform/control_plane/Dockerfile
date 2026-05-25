FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY . .
ENV PYTHONPATH=/app
CMD ["uv", "run", "uvicorn", "control_plane.main:app", "--host", "0.0.0.0", "--port", "8001"]
