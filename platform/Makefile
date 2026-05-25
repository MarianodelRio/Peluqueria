# Run all targets from the platform/ directory
.PHONY: run-control-plane run-data-plane up down clean test lint format help

run-control-plane:
	PYTHONPATH=. uv run uvicorn control_plane.main:app --host 0.0.0.0 --port 8001 --reload

run-data-plane:
	PYTHONPATH=. uv run uvicorn data_plane.main:app --host 0.0.0.0 --port 8002 --reload

up:
	docker compose up --build

down:
	docker compose down

clean:
	docker compose down -v

test:
	PYTHONPATH=. uv run pytest tests/ -v

lint:
	uv run ruff check . && PYTHONPATH=. uv run mypy control_plane data_plane shared

format:
	uv run ruff format .

help:
	@echo ""
	@echo "  run-control-plane   Arranca el Control Plane en localhost:8001"
	@echo "  run-data-plane      Arranca el Data Plane en localhost:8002"
	@echo "  up                  Levanta todos los servicios con Docker Compose"
	@echo "  down                Para y elimina los contenedores (datos persistidos)"
	@echo "  clean               Para contenedores Y borra la base de datos (down -v)"
	@echo "  test                Ejecuta los tests"
	@echo "  lint                Comprueba estilo y tipos"
	@echo "  format              Formatea el código"
	@echo "  help                Muestra esta ayuda"
	@echo ""
