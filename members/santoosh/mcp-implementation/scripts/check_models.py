"""Prove a model can actually call tools before you trust it.

A model can advertise tool support and still write the call out as ordinary
text, so the tool never runs and the agent quietly invents an answer. The only
reliable check is to hand it a tool and see whether the function executed.

    python scripts/check_models.py                  # test OPENROUTER_MODEL
    python scripts/check_models.py <model-id> ...   # test others before switching
"""

import asyncio
import sys
from pathlib import Path
from typing import Annotated

# Entry point: project root on sys.path before importing `core`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_framework import Agent, tool  # noqa: E402
from pydantic import Field  # noqa: E402

from core.llm import build_client  # noqa: E402

# Set by the tool when the model really invokes it, rather than describing it.
called_with: list[str] = []


@tool(approval_mode="never_require")
def get_notice_period(
    hire_type: Annotated[str, Field(description="Hire type name, e.g. 'Intern'.")],
) -> str:
    """Return the notice period in days for a hire type."""
    called_with.append(hire_type)
    return '{"hire_type": "Intern", "notice_period_days": 7}'


async def check(model: str | None) -> tuple[str, str]:
    """Ask one question that can only be answered by running the tool."""
    called_with.clear()
    agent = Agent(
        client=build_client(model),
        name="ToolCheck",
        instructions=(
            "You answer HR questions. You do not know any notice periods yourself. "
            "Always call get_notice_period() to find one. Never answer from memory."
        ),
        tools=[get_notice_period],
    )
    try:
        result = await asyncio.wait_for(
            agent.run("What is the notice period for an Intern?"), timeout=120
        )
    except asyncio.TimeoutError:
        return "TIMEOUT", "no response within 120s"
    except Exception as exc:  # noqa: BLE001 - report, do not crash the sweep
        return "ERROR", f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:150]}"

    answer = str(result).strip().replace("\n", " ")
    if not called_with:
        return "NO TOOL CALL", f"answered without running the tool: {answer[:110]}"
    if "7" not in answer:
        return "CALLED, BAD ANSWER", f"tool ran but answer lost the value: {answer[:110]}"
    return "PASS", f"tool ran with {called_with[0]!r}; answer contains 7"


async def main() -> None:
    # None means "whatever OPENROUTER_MODEL says" -- build_client resolves it.
    models: list[str | None] = list(sys.argv[1:]) or [None]

    for model in models:
        print(f"  {model or 'OPENROUTER_MODEL from .env'} ... ", end="", flush=True)
        verdict, detail = await check(model)
        print(f"{verdict}\n      {detail}")

    print("\nOnly PASS is safe to use. Set the winner as OPENROUTER_MODEL in .env.")


if __name__ == "__main__":
    asyncio.run(main())
