"""Agent prompts, stored as YAML and validated on load.

Prompts live in version-controlled YAML rather than inside Python string
literals for three reasons:

1. **They are reviewable.** A prompt change shows up as a readable diff instead
   of a wall of re-indented string.
2. **They are versioned.** Each file carries a `version`, which is recorded in
   the eval results, so "accuracy went from 82% to 91%" can be tied to a
   specific prompt revision rather than a vague memory.
3. **They are swappable.** Comparing two prompts for the same agent means
   pointing the loader at a different file, not editing code.

Every file is validated against `PromptSpec` at load time, so a typo in a key
fails immediately with a clear message rather than silently producing an agent
with no system prompt.
"""

from __future__ import annotations

from functools import cache
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ModelSpec(BaseModel):
    """Per-agent model settings. Names come from Settings, not from here."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    role: Literal["default", "analysis"] = Field(
        "default",
        description=(
            "Which configured model to use. 'default' is Settings.model_name "
            "(the cheap model everywhere); 'analysis' is Settings.model_name_analysis, "
            "which the brief allows upgrading only if evals show the cheap one is not enough."
        ),
    )
    max_output_tokens: int = Field(2000, gt=0, le=32_000)
    reasoning_effort: Literal["low", "medium", "high"] = "low"


class PromptSpec(BaseModel):
    """One agent's prompt definition."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: int = Field(..., ge=1, description="Bump on every meaningful change.")
    description: str
    model: ModelSpec = Field(default_factory=ModelSpec)
    tools: list[str] = Field(
        default_factory=list,
        description="MCP tool names this agent may call. Empty means no tools.",
    )
    system: str = Field(..., min_length=1, description="The system prompt.")

    def identifier(self) -> str:
        """Stable label for eval results, e.g. 'sql_agent@v3'."""
        return f"{self.name}@v{self.version}"


@cache
def load_prompt(name: str) -> PromptSpec:
    """Load and validate `<name>.yaml` from this package."""
    try:
        text = resources.files(__package__).joinpath(f"{name}.yaml").read_text("utf-8")
    except FileNotFoundError as exc:
        available = ", ".join(sorted(available_prompts()))
        raise FileNotFoundError(f"No prompt named {name!r}. Available: {available}") from exc

    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"{name}.yaml must contain a YAML mapping, got {type(raw).__name__}")

    spec = PromptSpec.model_validate(raw)
    if spec.name != name:
        raise ValueError(f"{name}.yaml declares name {spec.name!r}; the two must match")
    return spec


def available_prompts() -> list[str]:
    """Names of every prompt shipped with the package.

    Skips AppleDouble sidecars ("._name.yaml"). macOS writes these next to real
    files on filesystems that cannot store extended attributes, such as ExFAT
    and SMB shares. They match a *.yaml glob but contain binary, so without this
    filter the loader tries to parse one and dies on a UnicodeDecodeError.
    """
    return sorted(
        p.name.removesuffix(".yaml")
        for p in resources.files(__package__).iterdir()
        if p.name.endswith(".yaml") and not p.name.startswith("._")
    )
