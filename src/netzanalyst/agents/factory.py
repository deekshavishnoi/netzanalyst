"""Construct agents from a prompt file and the current settings.

The prompt YAML is the single source of truth for an agent's identity: its
instructions, which MCP tools it may call, which model tier it uses and how
many tokens it may spend. Nothing here hardcodes any of that, so changing an
agent means editing YAML, not Python.

Provider-agnostic by design. `OpenAIChatClient` speaks to Foundry
(`azure_endpoint`), to OpenAI directly, and to anything OpenAI-compatible such
as Ollama (`base_url`), so the same agent code runs on Azure during the trial
and locally afterwards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework_openai import OpenAIChatClient

from netzanalyst.config import Settings, get_settings
from netzanalyst.prompts import PromptSpec, load_prompt

if TYPE_CHECKING:
    from collections.abc import Collection


def resolve_model(spec: PromptSpec, settings: Settings) -> str:
    """Pick the configured model for this agent's declared tier.

    The brief's cost rule: the cheap model everywhere, and the larger one only
    for the analysis agent, and only once evals show the cheap one is not
    enough. The prompt declares a role; settings decide what that role means.
    """
    if spec.model.role == "analysis":
        return settings.model_name_analysis
    return settings.model_name


def build_chat_client(model: str, settings: Settings | None = None) -> OpenAIChatClient:
    """Build a chat client for the configured provider."""
    settings = settings or get_settings()
    provider = settings.model_provider

    if provider == "azure":
        if not settings.azure_openai_endpoint:
            raise ValueError(
                "MODEL_PROVIDER=azure requires AZURE_OPENAI_ENDPOINT. "
                "Set it in .env, or switch MODEL_PROVIDER to 'ollama' to run locally."
            )
        # No API key: DefaultAzureCredential picks up `az login` locally and the
        # managed identity once deployed, so no secret is ever in the process.
        from azure.identity import DefaultAzureCredential

        return OpenAIChatClient(
            model=model,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
            credential=DefaultAzureCredential(),
        )

    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("MODEL_PROVIDER=openai requires OPENAI_API_KEY.")
        return OpenAIChatClient(model=model, api_key=settings.openai_api_key)

    if provider == "ollama":
        # Ollama exposes an OpenAI-compatible API. It ignores the key, but the
        # client requires one to be present.
        return OpenAIChatClient(
            model=model,
            base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
            api_key="ollama",
        )

    raise ValueError(f"Unsupported MODEL_PROVIDER: {provider!r}")


def build_mcp_tool(
    allowed_tools: Collection[str] | None = None,
    settings: Settings | None = None,
) -> MCPStreamableHTTPTool:
    """Connect to the netzanalyst MCP server.

    `allowed_tools` is least privilege, straight from the prompt's `tools` list:
    the analysis agent gets no database access at all, and the verifier can read
    but cannot reach the live Energy-Charts API.
    """
    settings = settings or get_settings()
    return MCPStreamableHTTPTool(
        name="netzanalyst",
        url=f"http://localhost:{settings.mcp_port}/mcp",
        allowed_tools=list(allowed_tools) if allowed_tools else None,
        description="German electricity data: generation, consumption and day-ahead prices.",
        request_timeout=60,
    )


def build_agent(
    prompt_name: str,
    settings: Settings | None = None,
    *,
    mcp_tool: MCPStreamableHTTPTool | None = None,
) -> Agent:
    """Build one agent from its prompt file.

    Pass `mcp_tool` to share a single MCP connection across several agents
    rather than opening one per agent.
    """
    settings = settings or get_settings()
    spec = load_prompt(prompt_name)
    model = resolve_model(spec, settings)

    tools: list[MCPStreamableHTTPTool] = []
    if spec.tools:
        tools.append(mcp_tool or build_mcp_tool(spec.tools, settings))

    return Agent(
        client=build_chat_client(model, settings),
        name=spec.name,
        description=spec.description,
        instructions=spec.system,
        tools=tools or None,
        additional_properties={
            # Recorded on every answer so an eval result can be tied to the
            # exact prompt revision and model that produced it.
            "prompt_version": spec.identifier(),
            "model": model,
            "max_output_tokens": spec.model.max_output_tokens,
            "reasoning_effort": spec.model.reasoning_effort,
        },
    )
