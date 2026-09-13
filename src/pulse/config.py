"""Load config/product.yaml with optional environment overrides.

Env vars (optional):
  PULSE_CONFIG              path to YAML
  PULSE_WINDOW_WEEKS        int, must stay in 8–12
  PULSE_APP_STORE_ID        iOS numeric id (Phase 1)
  PULSE_OPERATOR_EMAIL      Gmail draft recipient
  PULSE_LLM_PROVIDER        anthropic | groq
  PULSE_LLM_MODEL           Claude or Groq catalog id (not OpenAI)
  ANTHROPIC_API_KEY         Anthropic Claude key (default provider)
  GROQ_API_KEY              optional Groq Cloud key
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from pulse.schemas import GROW_PLAY_ID

GROW_LOCALE = "en_IN"
WINDOW_WEEKS_MIN = 8
WINDOW_WEEKS_MAX = 12
DEFAULT_GROQ_MODEL = "qwen/qwen3.6-27b"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
_OPENAI_API_MARKERS = ("gpt-4o", "gpt-4.", "gpt-3.5", "o1-", "o3-")
_ALLOWED_MODEL_PREFIXES = ("groq", "anthropic")

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "product.yaml"


class ConfigError(ValueError):
    """Invalid or missing product configuration."""


class ProductConfig(BaseModel):
    name: str
    play_id: str
    play_hl: str
    app_store_id: str

    @field_validator("play_id")
    @classmethod
    def _groww_play_id(cls, play_id: str) -> str:
        if play_id != GROW_PLAY_ID:
            raise ValueError(f"play_id must be {GROW_PLAY_ID}")
        return play_id

    @field_validator("play_hl")
    @classmethod
    def _en_in(cls, play_hl: str) -> str:
        if play_hl != GROW_LOCALE:
            raise ValueError(f"play_hl must be {GROW_LOCALE}")
        return play_hl


class WindowConfig(BaseModel):
    weeks: int = Field(ge=WINDOW_WEEKS_MIN, le=WINDOW_WEEKS_MAX)


class LimitsConfig(BaseModel):
    max_themes: Literal[5] = 5
    pulse_themes: Literal[3] = 3
    quotes: Literal[3] = 3
    actions: Literal[3] = 3
    max_words: Literal[250] = 250


class OperatorConfig(BaseModel):
    email: str


class LlmConfig(BaseModel):
    provider: Literal["anthropic", "groq"] = "anthropic"
    model: str = DEFAULT_ANTHROPIC_MODEL

    @field_validator("model")
    @classmethod
    def _catalog_id(cls, model: str) -> str:
        raw = (model or "").strip()
        if not raw:
            raise ValueError("llm.model is required")
        if ":" in raw:
            prefix, rest = raw.split(":", 1)
            if prefix.lower() not in _ALLOWED_MODEL_PREFIXES or not rest.strip():
                raise ValueError("llm.model must be a Claude or Groq catalog id (not OpenAI)")
            raw = rest.strip()
        lowered = raw.lower()
        if any(marker in lowered for marker in _OPENAI_API_MARKERS):
            raise ValueError("OpenAI API models are not allowed")
        return raw


class AppConfig(BaseModel):
    product: ProductConfig
    window: WindowConfig
    limits: LimitsConfig
    operator: OperatorConfig
    llm: LlmConfig = Field(default_factory=LlmConfig)

    def groq_api_key(self) -> str | None:
        return os.environ.get("GROQ_API_KEY") or None

    def anthropic_api_key(self) -> str | None:
        return os.environ.get("ANTHROPIC_API_KEY") or None

    def llm_api_key(self) -> str | None:
        if self.llm.provider == "anthropic":
            return self.anthropic_api_key()
        return self.groq_api_key()


def default_config_path() -> Path:
    override = os.environ.get("PULSE_CONFIG")
    if override:
        return Path(override)
    return DEFAULT_CONFIG_PATH


def load_pulse_dotenv() -> None:
    """Load repo-root `.env` into the process. Does not override existing env vars."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = _REPO_ROOT / ".env"
    if path.is_file():
        load_dotenv(path, override=False)


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    product = dict(data.get("product") or {})
    window = dict(data.get("window") or {})
    operator = dict(data.get("operator") or {})
    llm = dict(data.get("llm") or {})

    if os.environ.get("PULSE_APP_STORE_ID"):
        product["app_store_id"] = os.environ["PULSE_APP_STORE_ID"]
    if os.environ.get("PULSE_WINDOW_WEEKS"):
        window["weeks"] = int(os.environ["PULSE_WINDOW_WEEKS"])
    if os.environ.get("PULSE_OPERATOR_EMAIL"):
        operator["email"] = os.environ["PULSE_OPERATOR_EMAIL"]
    if os.environ.get("PULSE_LLM_PROVIDER"):
        llm["provider"] = os.environ["PULSE_LLM_PROVIDER"]
    if os.environ.get("PULSE_LLM_MODEL"):
        llm["model"] = os.environ["PULSE_LLM_MODEL"]

    data = dict(data)
    data["product"] = product
    data["window"] = window
    data["operator"] = operator
    data["llm"] = llm
    return data


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("config YAML must be a mapping")
    try:
        return AppConfig.model_validate(_apply_env_overrides(raw))
    except Exception as exc:
        raise ConfigError(str(exc)) from exc
