from fastapi.testclient import TestClient

from regops_api.main import app

client = TestClient(app)


def test_create_run_accepts_required_multipart_fields() -> None:
    response = client.post(
        "/api/v1/runs",
        files={"regulation_file": ("rule.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"synthetic_ack": "true"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["state"] == "INGESTED"
    assert payload["regulation"]["source_filename"] == "rule.pdf"
    assert payload["regulation"]["synthetic"] is True
    assert payload["progress"]["documents_total"] == 1


def test_create_run_requires_multipart_fields_with_structured_error() -> None:
    response = client.post("/api/v1/runs")

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["message"] == "Request validation failed"
    assert {detail["location"][-1] for detail in payload["details"]} == {
        "regulation_file",
        "synthetic_ack",
    }


def test_create_run_rejects_non_pdf_content() -> None:
    response = client.post(
        "/api/v1/runs",
        files={"regulation_file": ("rule.pdf", b"not a pdf", "application/pdf")},
        data={"synthetic_ack": "true"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_PDF"


def test_create_run_requires_true_synthetic_acknowledgement() -> None:
    response = client.post(
        "/api/v1/runs",
        files={"regulation_file": ("rule.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"synthetic_ack": "false"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "SYNTHETIC_ACK_REQUIRED"
