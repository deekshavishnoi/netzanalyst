"""Typed settings, loaded once from the environment.

Everything configurable lives here rather than scattered `os.environ` lookups,
so a missing or malformed value fails at startup with a clear message instead of
halfway through an agent run.

Provider-agnostic on purpose: the same code runs against Foundry on Azure or a
local model after the trial ends.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelProvider = Literal["azure", "openai", "anthropic", "ollama"]


class Settings(BaseSettings):
    """Application settings, read from the environment and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # MODEL_NAME rather than model_name only; keep env names explicit.
        case_sensitive=False,
        # `model_` is Pydantic's own namespace; ours are deliberate.
        protected_namespaces=(),
    )

    # --- database ----------------------------------------------------------
    database_url: PostgresDsn = Field(
        ...,
        description="Full-privilege connection string. Ingest only, never the agents.",
    )
    database_url_readonly: PostgresDsn = Field(
        ...,
        description="SELECT-only connection string used by the MCP server.",
    )

    # --- model provider ----------------------------------------------------
    model_provider: ModelProvider = "azure"
    model_name: str = "gpt-5.4-mini"
    model_name_analysis: str = "gpt-5.4-mini"
    model_max_output_tokens: int = Field(2000, gt=0, le=32_000)
    model_reasoning_effort: Literal["low", "medium", "high"] = "low"

    # --- Azure / Foundry ---------------------------------------------------
    azure_ai_project_endpoint: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str | None = Field(
        None,
        description="Azure OpenAI API version. Leave unset to use the client's default.",
    )

    # --- non-Azure fallbacks ----------------------------------------------
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # --- MCP ---------------------------------------------------------------
    mcp_port: int = Field(3000, gt=0, lt=65_536)
    mcp_max_rows: int = Field(1000, gt=0)
    mcp_query_timeout_ms: int = Field(10_000, gt=0)
    energy_charts_base_url: str = "https://api.energy-charts.info"

    # --- observability -----------------------------------------------------
    applicationinsights_connection_string: str | None = None

    @field_validator("database_url_readonly")
    @classmethod
    def _readonly_url_uses_readonly_role(cls, value: PostgresDsn) -> PostgresDsn:
        """Catch the mistake of pointing the agents at the owning role.

        The whole read-only guarantee rests on this connection using the
        restricted role, so a typo here would quietly remove a security layer.
        """
        # PostgresDsn is a multi-host URL; the credentials live under hosts().
        hosts = value.hosts()
        username = hosts[0].get("username") if hosts else None
        if username and not username.endswith("_ro"):
            raise ValueError(
                f"database_url_readonly must use the read-only role "
                f"(a username ending in '_ro'), got {username!r}. "
                f"Pointing the agents at the owning role removes the read-only guarantee."
            )
        return value


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide settings, loading them on first use."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
