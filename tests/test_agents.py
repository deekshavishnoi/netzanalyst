"""Agent wiring. No model is called: these assert how agents are assembled."""

import pytest

from netzanalyst.agents import build_agent, build_chat_client, resolve_model
from netzanalyst.config import Settings
from netzanalyst.prompts import load_prompt

OWNER = "postgresql://netzanalyst:pw@127.0.0.1:5432/netzanalyst"
READONLY = "postgresql://netzanalyst_ro:pw@127.0.0.1:5432/netzanalyst"

AGENTS = ["orchestrator", "sql_agent", "analysis_agent", "verifier_agent"]


def _settings(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "database_url": OWNER,
        "database_url_readonly": READONLY,
        "model_provider": "ollama",
        "model_name": "cheap-model",
        "model_name_analysis": "expensive-model",
        **overrides,
    }
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", AGENTS)
def test_every_agent_builds(name: str) -> None:
    agent = build_agent(name, _settings())
    assert agent.name == name
    # Agent Framework keeps the system prompt on default_options, not as an
    # attribute on the agent itself.
    assert (agent.default_options or {}).get("instructions")


@pytest.mark.parametrize("name", AGENTS)
def test_agents_record_their_prompt_version(name: str) -> None:
    """Eval results must be attributable to an exact prompt revision."""
    agent = build_agent(name, _settings())
    assert agent.additional_properties["prompt_version"] == load_prompt(name).identifier()


def test_only_the_analysis_agent_gets_the_expensive_model() -> None:
    """The brief's cost rule, enforced rather than trusted to the prompt."""
    settings = _settings()
    for name in AGENTS:
        model = resolve_model(load_prompt(name), settings)
        expected = "expensive-model" if name == "analysis_agent" else "cheap-model"
        assert model == expected, f"{name} resolved to {model}"


def test_tool_access_is_least_privilege() -> None:
    """Each agent may call only the MCP tools its prompt declares."""
    settings = _settings()
    expected = {
        "orchestrator": set(),
        "sql_agent": {"get_schema", "run_sql", "fetch_energy_charts"},
        "analysis_agent": set(),
        "verifier_agent": {"get_schema", "run_sql"},
    }
    for name, tools in expected.items():
        mcp = build_agent(name, settings).mcp_tools or []
        if not tools:
            assert not mcp, f"{name} should have no MCP access"
            continue
        assert set(mcp[0].allowed_tools or []) == tools, f"{name} has the wrong tool set"


def test_the_analysis_agent_cannot_reach_the_database() -> None:
    """It must compute from rows it is given, never fetch its own."""
    assert not (build_agent("analysis_agent", _settings()).mcp_tools or [])


def test_the_verifier_cannot_reach_the_live_api() -> None:
    """Verification must be against the same data the answer used."""
    mcp = build_agent("verifier_agent", _settings()).mcp_tools or []
    assert "fetch_energy_charts" not in set(mcp[0].allowed_tools or [])


def test_azure_provider_demands_an_endpoint() -> None:
    """Failing at startup beats failing on the first question."""
    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        build_chat_client("gpt-4.1-mini", _settings(model_provider="azure"))


def test_openai_provider_demands_a_key() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_chat_client("gpt-4.1-mini", _settings(model_provider="openai", openai_api_key=None))


def test_ollama_needs_no_credentials() -> None:
    """The brief requires the project to run locally after the trial ends."""
    assert build_chat_client("llama3.2", _settings()) is not None
