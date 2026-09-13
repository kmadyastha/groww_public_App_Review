"""Chat-model factory. Anthropic Claude is the default; Groq remains optional.

Never uses the OpenAI API (`api.openai.com` / `OPENAI_API_KEY`).
"""

from __future__ import annotations

from typing import Any

from pulse.config import AppConfig, ConfigError


def response_text(raw: Any) -> Any:
    """Unwrap LangChain message content (string or content-block list)."""
    if hasattr(raw, "content"):
        raw = raw.content
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
            elif hasattr(block, "text"):
                parts.append(str(block.text))
        return "".join(parts)
    return raw


def chat_model(config: AppConfig, **kwargs: Any) -> Any:
    """Return a LangChain chat model for `config.llm.provider`."""
    if config.llm.provider == "anthropic":
        return anthropic_chat_model(config, **kwargs)
    if config.llm.provider == "groq":
        return groq_chat_model(config, **kwargs)
    raise ConfigError(f"unsupported llm.provider: {config.llm.provider}")


def anthropic_chat_model(config: AppConfig, **kwargs: Any) -> Any:
    """Return `ChatAnthropic` bound to `config.llm.model`."""
    if config.llm.provider != "anthropic":
        raise ConfigError("llm.provider must be anthropic")
    api_key = config.anthropic_api_key()
    if not api_key:
        raise ConfigError("ANTHROPIC_API_KEY is required for intelligence nodes")
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise ConfigError(
            "langchain-anthropic is required (pip install langchain-anthropic)"
        ) from exc
    params = {
        "temperature": 0,
        "max_tokens": 4096,
        "max_retries": 2,
        **kwargs,
    }
    return ChatAnthropic(model=config.llm.model, api_key=api_key, **params)


def groq_chat_model(config: AppConfig, **kwargs: Any) -> Any:
    """Return a LangChain `ChatGroq` bound to `config.llm.model`."""
    if config.llm.provider != "groq":
        raise ConfigError("llm.provider must be groq")
    api_key = config.groq_api_key()
    if not api_key:
        raise ConfigError("GROQ_API_KEY is required for intelligence nodes")
    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:
        raise ConfigError("langchain-groq is required (pip install langchain-groq)") from exc
    params = {
        "temperature": 0,
        "max_tokens": 512,
        "max_retries": 0,
        **kwargs,
    }
    return ChatGroq(model=config.llm.model, groq_api_key=api_key, **params)
