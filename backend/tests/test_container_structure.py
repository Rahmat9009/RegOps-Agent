from pathlib import Path


def test_dockerfile_is_python312_locked_nonroot_and_cloud_run_ready() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.startswith("FROM python:3.12.")
    assert "requirements-runtime.lock ./" in dockerfile
    assert "pip install --no-cache-dir -r requirements-runtime.lock" in dockerfile
    assert "pip install --no-cache-dir --no-deps ." in dockerfile
    assert "COPY src ./src" in dockerfile
    assert "USER regops" in dockerfile
    assert "--host 0.0.0.0 --port ${PORT}" in dockerfile
