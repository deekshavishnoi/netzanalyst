"""Settings validation, especially the guards that protect a security property."""

import pytest
from pydantic import ValidationError

from netzanalyst.config import Settings

OWNER = "postgresql://netzanalyst:pw@127.0.0.1:5432/netzanalyst"
READONLY = "postgresql://netzanalyst_ro:pw@127.0.0.1:5432/netzanalyst"


def _settings(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "database_url": OWNER,
        "database_url_readonly": READONLY,
        **overrides,
    }
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def test_defaults_match_the_brief() -> None:
    s = _settings()
    assert s.model_provider == "azure"
    assert s.model_name == "gpt-5.4-mini"
    # The brief: the cheap model everywhere by default.
    assert s.model_name_analysis == "gpt-5.4-mini"
    assert s.model_reasoning_effort == "low"


def test_readonly_url_must_use_the_readonly_role() -> None:
    """Pointing the agents at the owning role would remove a security layer."""
    with pytest.raises(ValidationError, match="read-only role"):
        _settings(database_url_readonly=OWNER)


def test_readonly_url_accepts_the_readonly_role() -> None:
    assert _settings(database_url_readonly=READONLY).database_url_readonly


def test_rejects_an_unknown_model_provider() -> None:
    with pytest.raises(ValidationError):
        _settings(model_provider="not-a-provider")


def test_rejects_an_out_of_range_port() -> None:
    with pytest.raises(ValidationError):
        _settings(mcp_port=70_000)
