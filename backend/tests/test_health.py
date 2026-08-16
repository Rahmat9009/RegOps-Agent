from fastapi.testclient import TestClient

from regops_api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_all_six_workflow_operations_use_structured_stubs() -> None:
    responses = [
        client.get("/api/v1/runs/run-1"),
        client.get("/api/v1/runs/run-1/findings"),
        client.get("/api/v1/findings/finding-1"),
        client.post("/api/v1/actions/action-1/preview"),
        client.post(
            "/api/v1/approvals/approval-1/decision",
            json={"decision": "reject"},
        ),
        client.get("/api/v1/runs/run-1/audit"),
    ]

    for response in responses:
        assert response.status_code == 501
        assert response.json() == {
            "code": "NOT_IMPLEMENTED",
            "message": "This operation is declared for integration but begins after Phase 0",
            "details": None,
        }
