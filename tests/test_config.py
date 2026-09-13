"""Phase 0 config loader (eval E0-02, E0-05, E0-06)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from pulse.config import (
    WINDOW_WEEKS_MAX,
    WINDOW_WEEKS_MIN,
    AppConfig,
    ConfigError,
    LimitsConfig,
    LlmConfig,
    default_config_path,
    load_config,
)
from pulse.schemas import GROW_APP_STORE_ID, GROW_PLAY_ID

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_pulse_env(monkeypatch):
    for key in (
        "PULSE_CONFIG",
        "PULSE_WINDOW_WEEKS",
        "PULSE_APP_STORE_ID",
        "PULSE_OPERATOR_EMAIL",
        "PULSE_LLM_MODEL",
        "PULSE_LLM_PROVIDER",
        "GROQ_API_KEY",
        "ANTHROPIC_API_KEY",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_product_yaml_groww_ids_and_limits():
    cfg = load_config()
    assert cfg.product.name == "Groww"
    assert cfg.product.play_id == GROW_PLAY_ID
    assert cfg.product.play_hl == "en_IN"
    assert cfg.product.app_store_id == GROW_APP_STORE_ID
    assert WINDOW_WEEKS_MIN <= cfg.window.weeks <= WINDOW_WEEKS_MAX
    assert cfg.window.weeks == 10
    assert cfg.limits.max_themes == 5
    assert cfg.limits.pulse_themes == 3
    assert cfg.limits.quotes == 3
    assert cfg.limits.actions == 3
    assert cfg.limits.max_words == 250
    assert cfg.operator.email == "karthik.katu@gmail.com"
    assert cfg.llm.provider == "anthropic"
    assert cfg.llm.model == "claude-sonnet-5"


def test_default_config_path_is_repo_product_yaml():
    assert default_config_path() == REPO_ROOT / "config" / "product.yaml"
    assert default_config_path().is_file()


def test_env_overrides_operator_and_weeks(monkeypatch):
    monkeypatch.setenv("PULSE_OPERATOR_EMAIL", "me@example.com")
    monkeypatch.setenv("PULSE_WINDOW_WEEKS", "8")
    monkeypatch.setenv("PULSE_APP_STORE_ID", "1234567890")
    monkeypatch.setenv("PULSE_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("PULSE_LLM_MODEL", "claude-sonnet-5")
    cfg = load_config()
    assert cfg.operator.email == "me@example.com"
    assert cfg.window.weeks == 8
    assert cfg.product.app_store_id == "1234567890"
    assert cfg.llm.provider == "anthropic"
    assert cfg.llm.model == "claude-sonnet-5"


def test_openai_models_are_rejected():
    with pytest.raises(ValidationError):
        LlmConfig(model="openai:gpt-4o-mini")
    with pytest.raises(ValidationError):
        LlmConfig(model="gpt-4o-mini")
    claude = LlmConfig(provider="anthropic", model="anthropic:claude-sonnet-5")
    assert claude.model == "claude-sonnet-5"
    assert LlmConfig(provider="groq", model="qwen/qwen3.6-27b").provider == "groq"
    assert LlmConfig(provider="groq", model="groq:openai/gpt-oss-20b").model == "openai/gpt-oss-20b"


def test_env_openai_model_override_is_rejected(monkeypatch):
    monkeypatch.setenv("PULSE_LLM_MODEL", "openai:gpt-4o-mini")
    with pytest.raises(ConfigError):
        load_config()


def test_chat_model_requires_anthropic_key():
    from pulse.llm import chat_model

    cfg = load_config()
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        chat_model(cfg)


def test_groq_chat_model_requires_api_key():
    from pulse.llm import groq_chat_model

    cfg = load_config()
    groq_cfg = cfg.model_copy(
        update={"llm": LlmConfig(provider="groq", model="qwen/qwen3.6-27b")}
    )
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        groq_chat_model(groq_cfg)


def test_env_weeks_outside_8_12_is_rejected(monkeypatch):
    monkeypatch.setenv("PULSE_WINDOW_WEEKS", "4")
    with pytest.raises(ConfigError):
        load_config()


def test_limits_are_not_tunable():
    with pytest.raises(ValidationError):
        LimitsConfig(
            max_themes=6,
            pulse_themes=3,
            quotes=3,
            actions=3,
            max_words=250,
        )


def test_wrong_play_id_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "product": {
                    "name": "Groww",
                    "play_id": "com.other.app",
                    "play_hl": "en_IN",
                    "app_store_id": "PLACEHOLDER",
                },
                "window": {"weeks": 10},
                "limits": {
                    "max_themes": 5,
                    "pulse_themes": 3,
                    "quotes": 3,
                    "actions": 3,
                    "max_words": 250,
                },
                "operator": {"email": "alias@example.com"},
            }
        )


def test_missing_config_file_raises(tmp_path):
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(missing)


def test_env_example_has_claude_key_not_openai():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").lower()
    assert "anthropic_api_key" in text
    for forbidden in (
        "openai_api_key",
        "google",
        "gmail",
        "oauth",
        "googleapis",
        "client_secret",
        "refresh_token",
    ):
        assert forbidden not in text


def test_gitignore_covers_raw_data_and_dotenv():
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in text
    assert "data/raw" in text
    assert "__pycache__" in text
