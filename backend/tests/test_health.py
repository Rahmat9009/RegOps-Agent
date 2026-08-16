from fastapi.testclient import TestClient

from regops_api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_phase_zero_stub_uses_structured_error() -> None:
    response = client.get("/api/v1/runs/run-1")

    assert response.status_code == 501
    assert response.json() == {
        "code": "NOT_IMPLEMENTED",
        "message": "This operation is declared for integration but begins after Phase 0",
        "details": None,
    }
