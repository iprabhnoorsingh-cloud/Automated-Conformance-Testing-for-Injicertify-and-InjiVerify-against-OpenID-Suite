from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from tests.conftest import AUTH_HEADERS

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_status_ok():
    response = client.get("/health")
    assert response.json() == {"status": "ok"}


def test_root_returns_app_name():
    response = client.get("/", headers=AUTH_HEADERS)
    assert response.json()["name"] == settings.app_name
