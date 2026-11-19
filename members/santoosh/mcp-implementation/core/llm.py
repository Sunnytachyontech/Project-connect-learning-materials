"""The OpenRouter chat client, shared by both agents.

OpenRouter is OpenAI-compatible, so the stock Chat Completions client works
once base_url points at it -- no OpenRouter-specific package needed.
"""

import os
from pathlib import Path

from agent_framework.openai import OpenAIChatCompletionClient
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = "https://openrouter.ai/api/v1"


def build_client(model: str | None = None) -> OpenAIChatCompletionClient:
    """Chat client for OPENROUTER_MODEL, or an explicit model id.

    The model MUST support tool calling, or the agent silently never reaches
    the database -- it just makes something up. Prove a new one works with
    `python check_models.py` before putting it in .env.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is empty -- add your key to .env.")

    model = model or os.getenv("OPENROUTER_MODEL", "").strip()
    if not model:
        raise SystemExit("OPENROUTER_MODEL is empty -- set one in .env.")

    # OpenAIChatCompletionClient, not OpenAIChatClient: the latter targets
    # OpenAI's Responses API, which OpenRouter does not implement, and fails
    # with "400 - previous_response_id is not ...".
    return OpenAIChatCompletionClient(model=model, api_key=api_key, base_url=BASE_URL)
def explain_model_error(exc: Exception) -> str:
    """Turn a provider failure into one actionable line.

    This is for whoever is running the demo, not for the HR user, so naming
    OpenRouter and the setting to change is the helpful thing to do. RULE 11
    governs what the *agent* says; it does not apply here.
    """
    text = str(exc)
    if "429" in text or "rate limit" in text.lower():
        return (
            "OpenRouter rate limit reached. The free tier caps requests per DAY "
            "across every :free model, so switching OPENROUTER_MODEL to another "
            "free one will not help. Wait for the daily reset, or add credits at "
            "https://openrouter.ai/settings/credits"
        )
    if "401" in text or "No auth credentials" in text:
        return "OpenRouter rejected the key. Check OPENROUTER_API_KEY in .env."
    if "404" in text:
        return (
            "OpenRouter has no endpoint for this model. Check OPENROUTER_MODEL, "
            "and for a :free model enable the data policy at "
            "https://openrouter.ai/settings/privacy"
        )
    return f"The model call failed: {text.strip().splitlines()[0][:160]}"


