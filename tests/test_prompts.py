"""Every shipped prompt must load, validate, and stay internally consistent."""

import pytest

from netzanalyst.prompts import PromptSpec, available_prompts, load_prompt

EXPECTED = {"orchestrator", "sql_agent", "analysis_agent", "verifier_agent"}
# Must match the tools the MCP server actually registers.
MCP_TOOLS = {"get_schema", "run_sql", "fetch_energy_charts"}


def test_all_four_agents_have_a_prompt() -> None:
    assert EXPECTED.issubset(set(available_prompts()))


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_prompt_loads_and_validates(name: str) -> None:
    spec = load_prompt(name)
    assert isinstance(spec, PromptSpec)
    assert spec.name == name
    assert spec.version >= 1
    assert spec.system.strip(), "system prompt must not be empty"
    assert spec.identifier() == f"{name}@v{spec.version}"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_prompts_only_reference_real_mcp_tools(name: str) -> None:
    """A prompt naming a tool the server does not expose is a silent failure."""
    unknown = set(load_prompt(name).tools) - MCP_TOOLS
    assert not unknown, f"{name} references non-existent tools: {sorted(unknown)}"


def test_only_the_analysis_agent_may_use_the_expensive_model() -> None:
    """The brief: gpt-5.4-mini everywhere, the bigger model only for analysis."""
    for name in available_prompts():
        spec = load_prompt(name)
        if spec.model.role == "analysis":
            assert name == "analysis_agent", (
                f"{name} claims the 'analysis' model role; the brief reserves it "
                f"for the analysis agent only."
            )


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_prompt_caps_its_output(name: str) -> None:
    """The brief requires max output tokens set on every agent, to bound cost."""
    assert 0 < load_prompt(name).model.max_output_tokens <= 32_000


def test_verifier_can_check_the_database_itself() -> None:
    """A verifier that cannot re-query can only re-read, which catches less."""
    assert "run_sql" in load_prompt("verifier_agent").tools


def test_unknown_prompt_names_the_alternatives() -> None:
    with pytest.raises(FileNotFoundError, match="Available:"):
        load_prompt("does_not_exist")
