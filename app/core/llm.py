"""LLM access — the single seam through which the agent reaches its model.

The model is ALWAYS the Anthropic API (ChatAnthropic). This holds both locally
(FastAPI/uvicorn) and when the agent is hosted on **Bedrock AgentCore Runtime** —
AgentCore is the serverless *host* for the agent, not a model provider. We do not
call Bedrock-served Claude. The same ANTHROPIC_API_KEY is supplied wherever the
agent runs.

Agent nodes and guardrails MUST go through `get_chat_model()` /
`get_guardrail_model()` and never import `anthropic` / instantiate a chat model
directly (AGENT.md §2), so model choice and params live in exactly one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


def get_chat_model(
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    streaming: bool = True,
) -> BaseChatModel:
    """Return the primary agent chat model (Anthropic API)."""
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=model or settings.anthropic_model_id,
        api_key=settings.anthropic_api_key,
        max_tokens=max_tokens,
        streaming=streaming,
        timeout=60,
        stop=None,
    )


def get_guardrail_model(*, max_tokens: int = 1024, streaming: bool = False) -> BaseChatModel:
    """Cheap/fast model (Haiku) for scope classification and lightweight checks."""
    return get_chat_model(
        model=settings.anthropic_guardrail_model_id,
        max_tokens=max_tokens,
        streaming=streaming,
    )
