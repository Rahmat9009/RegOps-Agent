import pytest

from regops_api.in_memory import InMemoryRepositories


def test_in_memory_adapter_rejects_production_purpose() -> None:
    with pytest.raises(ValueError, match="non-production"):
        InMemoryRepositories(purpose="production")  # type: ignore[arg-type]


def test_in_memory_adapter_is_explicitly_labelled_non_production() -> None:
    repositories = InMemoryRepositories.for_development()

    assert repositories.is_production is False
    assert repositories.purpose == "development"
