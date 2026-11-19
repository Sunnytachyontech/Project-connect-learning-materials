"""Intern 3/7 - multi-turn MAF demo, backed by PostgreSQL over MCP.

Extends the 2/7 agent:
  * remembers earlier turns (one session for the whole conversation)
  * asks for missing hire-request details instead of guessing
  * reads hire types from, and writes hire requests to, a local PostgreSQL
    database -- reached through an MCP server, not through direct SQL here

The database lives behind `pg_mcp_server.py`. This file spawns that script as a
subprocess and talks MCP to it over stdin/stdout, so the agent process has no
connection string, no psycopg import and no SQL of its own.

The model is an OpenRouter one, configured in .env -- see llm.py.

Setup:  python setup_db.py      (once, creates the tables)
Run:    python multi_agent.py
Type  /reset  to start a fresh session, or  exit  to quit.
"""

import asyncio
import sys
from pathlib import Path

# Entry point: put the project root on sys.path so `core` and `server` import
# cleanly when this file is run directly. Must happen before those imports.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_framework import Agent, MCPStdioTool, Message  # noqa: E402

# Not re-exported at the top level in agent-framework 1.25.0.
from agent_framework._mcp import MCPSpecificApproval  # noqa: E402

from core.llm import build_client, explain_model_error  # noqa: E402
from core.prompt import INSTRUCTIONS  # noqa: E402

MCP_SERVER = ROOT / "server" / "pg_mcp_server.py"


def build_postgres_tool() -> MCPStdioTool:
    """The MCP client: launches pg_mcp_server.py and adopts its tools as the
    agent's own. `sys.executable` keeps the server on this venv's interpreter."""
    return MCPStdioTool(
        name="postgres_hr",
        command=sys.executable,
        # -u keeps the subprocess stdio unbuffered, so MCP frames are not held
        # in a pipe buffer while the agent waits for a reply.
        args=["-u", str(MCP_SERVER)],
        description="HR hire types and hire requests stored in PostgreSQL.",
        # Reads run unattended; the one tool that writes to the database stops
        # and asks first. `default` is set explicitly -- omitting it emits a
        # FutureWarning, because the implicit fallback may change.
        approval_mode=MCPSpecificApproval(
            always_require_approval=["create_hire_request"],
            default="never_require",
        ),
    )



def build_agent(postgres: MCPStdioTool) -> Agent:
    return Agent(
        client=build_client(),
        name="HireRequestAgent",
        instructions=INSTRUCTIONS,
        tools=[postgres],
    )


def approval_requests(result) -> list:
    """Pull any pending approval requests out of an agent response.

    A tool marked always_require does not run. The framework returns a
    `function_approval_request` instead, carrying the exact call the model
    wanted to make, and waits for an answer.
    """
    return [
        content
        for message in result.messages
        for content in message.contents
        if getattr(content, "type", None) == "function_approval_request"
    ]


def ask_human(request) -> bool:
    """Show the pending write and ask whether to let it through."""
    call = request.function_call
    arguments = call.parse_arguments() or {}

    print("\n  +-- APPROVAL REQUIRED ---------------------------------------")
    print(f"  |  tool: {call.name}")
    if arguments:
        print("  |  data to be written to the database:")
        width = max(len(key) for key in arguments)
        for key, value in arguments.items():
            print(f"  |      {key:<{width}} = {value!r}")
    else:
        print("  |  (no arguments)")
    print("  +------------------------------------------------------------")

    answer = input("  Approve this write? [y/N]: ").strip().lower()
    approved = answer in {"y", "yes"}
    print("  -> APPROVED, writing.\n" if approved else "  -> REJECTED, nothing written.\n")
    return approved


async def run_turn(agent: Agent, session, user_input):
    """Run one turn, pausing for human approval as often as the model asks.

    Looping matters: after an approval is answered the model may call another
    gated tool, so one check is not enough.
    """
    result = await agent.run(user_input, session=session)

    while requests := approval_requests(result):
        answers = [
            request.to_function_approval_response(approved=ask_human(request))
            for request in requests
        ]
        # The answers go back as a user message; the framework matches them to
        # the pending calls and either runs or refuses each one.
        result = await agent.run(Message(role="user", contents=answers), session=session)

    return result


def stored_message_count(session) -> int:
    """How many messages MAF has saved in this session so far.
    The default in-memory provider keeps them in session.state['in_memory']['messages']."""
    return len(session.state.get("in_memory", {}).get("messages", []))


async def main() -> None:
    postgres = build_postgres_tool()

    # Entering the context manager starts pg_mcp_server.py and runs the MCP
    # handshake; leaving it shuts the subprocess down. Everything that uses the
    # agent has to happen inside this block.
    async with postgres:
        tool_names = ", ".join(sorted(f.name for f in postgres.functions))
        print(f"MCP server connected: {postgres.name} -> [{tool_names}]")

        agent = build_agent(postgres)
        session = agent.create_session()  # one session = one conversation
        print(f"New session: {session.session_id}")

        turn = 0
        while True:
            user_input = input("\nYou (/reset for new session, exit to quit): ").strip()
            if user_input.lower() == "exit":
                break
            if user_input.lower() == "/reset":
                session = agent.create_session()  # new session = no memory of the old chat
                turn = 0
                print(f"New session: {session.session_id} (database is unchanged)")
                continue
            if not user_input:
                continue

            turn += 1
            try:
                result = await run_turn(agent, session, user_input)
            except Exception as exc:  # noqa: BLE001 - keep the session alive
                # A provider failure is an operator problem, not a crash. Print
                # something actionable and stay in the loop so the conversation
                # (and the MCP server) survive a blip.
                print(f"\n  [model unavailable] {explain_model_error(exc)}")
                continue

            print(f"Agent: {result}")
            print(f"  (turn {turn}, {stored_message_count(session)} messages stored in session)")


if __name__ == "__main__":
    asyncio.run(main())
