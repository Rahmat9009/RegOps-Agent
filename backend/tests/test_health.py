from fastapi.testclient import TestClient

from regops_api.main import app, create_app
from tests.runtime_helpers import make_runtime

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_all_six_runtime_operations_are_implemented_and_use_structured_404s() -> None:
    runtime = make_runtime()
    runtime_client = TestClient(create_app(settings=runtime.settings, runtime=runtime))
    responses = [
        runtime_client.get("/api/v1/runs/run-1"),
        runtime_client.get("/api/v1/runs/run-1/findings"),
        runtime_client.get("/api/v1/findings/finding-1"),
        runtime_client.post("/api/v1/actions/action-1/preview"),
        runtime_client.post(
            "/api/v1/approvals/approval-1/decision",
            json={"decision": "reject"},
        ),
        runtime_client.get("/api/v1/runs/run-1/audit"),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {
            "code": "NOT_FOUND",
            "message": "Requested resource was not found",
            "details": None,
        }
