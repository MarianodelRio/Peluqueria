from starlette.testclient import TestClient

from control_plane.main import app as cp_app


def test_control_plane_health() -> None:
    client = TestClient(cp_app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
