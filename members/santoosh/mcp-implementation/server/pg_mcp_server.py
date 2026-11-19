"""Local PostgreSQL MCP server (stdio transport).

This is the *server* half of the demo. It owns the database connection and
exposes a small, named set of HR tools over the Model Context Protocol.
`multi_agent.py` is the *client* half -- it spawns this file as a subprocess
and talks MCP to it over stdin/stdout, so the agent never imports psycopg and
never sees a connection string.

Run it by hand to check it starts (it will sit waiting for MCP traffic on
stdin -- Ctrl+C to stop):

    python server/pg_mcp_server.py

Connection settings come from .env, via core/db.py. Run
`python scripts/setup_db.py` once first to create the tables.
"""

import functools
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

# Entry point: this file is spawned as a subprocess, so put the project root on
# sys.path before importing `core`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from pydantic import Field  # noqa: E402

from core.db import connect  # noqa: E402

PLACEHOLDERS = {"", "unknown", "n/a", "na", "none", "tbd", "not provided", "?"}

MAX_ROWS = 200  # hard cap on anything run_query hands back to the model


def as_json(value: Any) -> str:
    """Tool results must be text. `default=str` keeps dates/decimals readable."""
    return json.dumps(value, default=str)


def db_errors(func: Callable[..., str]) -> Callable[..., str]:
    """Turn a database failure into a sentence the model can act on.

    Without this an OperationalError escapes as an MCP protocol error and the
    agent just sees "tool failed". Returning text keeps the agent on RULE 4:
    tell the user it could not be done, and offer to try again.

    The detail goes to stderr for whoever is running the server, and never to
    the model. Raw psycopg text names hosts, ports, columns and constraints,
    and anything the model is told it may repeat to the user.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return func(*args, **kwargs)
        except psycopg.Error as exc:
            kind = (
                "DB_UNAVAILABLE"
                if isinstance(exc, psycopg.OperationalError)
                else "DB_ERROR"
            )
            print(
                f"[{kind}] {func.__name__}: {str(exc).strip().splitlines()[0]}",
                file=sys.stderr,
                flush=True,
            )
            return (
                f"{kind}: the request could not be completed. Tell the user the "
                "system is unavailable right now and offer to try again. Do not "
                "mention databases, SQL or this error code."
            )

    return wrapper


server = MCPServer(
    name="postgres-hr",
    instructions=(
        "HR data stored in a local PostgreSQL database: hire types (reference "
        "data) and hire requests (records this agent creates)."
    ),
)


@server.tool()
@db_errors
def list_hire_types() -> str:
    """List every hire type with its description, probation period, notice
    period and benefits eligibility. Use this when the user asks what hire
    types exist."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, description, probation_months, notice_period_days, "
            "benefits_eligible FROM hire_types ORDER BY name"
        )
        return as_json(cur.fetchall())


@server.tool()
@db_errors
def get_hire_type(
    name: Annotated[str, Field(description="Hire type name, e.g. 'Full-time'.")],
) -> str:
    """Look up one hire type by name. Use this whenever the user asks about the
    probation period, notice period, benefits or meaning of a hire type."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, description, probation_months, notice_period_days, "
            "benefits_eligible FROM hire_types WHERE lower(name) = lower(%s)",
            (name.strip(),),
        )
        row = cur.fetchone()
        if row:
            return as_json(row)

        cur.execute("SELECT name FROM hire_types ORDER BY name")
        available = ", ".join(r["name"] for r in cur.fetchall())
    return f"HIRE_TYPE_NOT_FOUND. Available hire types: {available}"


@server.tool()
@db_errors
def create_hire_request(
    name: Annotated[
        str | None,
        Field(
            description="Full name of the person to hire, exactly as the user "
            "gave it. Omit this argument if the user has not given a name."
        ),
    ] = None,
    role: Annotated[
        str | None,
        Field(
            description="Job role or title, exactly as the user gave it. "
            "Omit this argument if the user has not given a role."
        ),
    ] = None,
    location: Annotated[
        str | None,
        Field(
            description="Work location (city), exactly as the user gave it. "
            "Omit this argument if the user has not given a location."
        ),
    ] = None,
) -> str:
    """Save a hire request to the database from details the user has actually
    given. Pass only the values the user stated. Omit any argument the user has
    not given -- never substitute a guess, a default, or an example value from
    another tool."""
    fields = {"name": name, "role": role, "location": location}
    missing = [
        key
        for key, value in fields.items()
        if value is None or value.strip().lower() in PLACEHOLDERS
    ]
    if missing:
        # Guardrail: a value the user never gave must be absent, not invented.
        # Rejecting here, server-side, means the bad row never reaches Postgres.
        return (
            f"MISSING_FIELDS: {', '.join(missing)}. "
            "Ask the user for these, one at a time. Do not guess."
        )

    values = (name.strip(), role.strip(), location.strip())

    with connect() as conn, conn.cursor() as cur:
        # Guardrail: the same person, role and location on the same day is a
        # repeat call, not a second vacancy. A small model that is unsure its
        # first call landed will happily call again -- this makes that a no-op.
        # The unique index created by setup_db.py backs this up, so two calls
        # racing each other cannot both get past this check.
        cur.execute(
            "SELECT id FROM hire_requests "
            "WHERE lower(name) = lower(%s) AND lower(role) = lower(%s) "
            "AND lower(location) = lower(%s) AND created_on = current_date",
            values,
        )
        existing = cur.fetchone()
        if existing:
            return (
                f"DUPLICATE_HIRE_REQUEST: an identical request was already saved "
                f"today as id {existing['id']}. Nothing was written. Tell the user "
                "it already exists and give them that id -- do not call this tool again."
            )

        cur.execute(
            "INSERT INTO hire_requests (name, role, location) VALUES (%s, %s, %s) "
            "RETURNING id, status, name, role, location, created_on",
            values,
        )
        return as_json(cur.fetchone())


@server.tool()
@db_errors
def list_hire_requests() -> str:
    """List the hire requests saved in the database, newest first. Use this when
    the user asks what has been requested or drafted so far."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, name, role, location, created_on "
            "FROM hire_requests ORDER BY id DESC LIMIT %s",
            (MAX_ROWS,),
        )
        rows = cur.fetchall()
    if not rows:
        return "NO_HIRE_REQUESTS: the database has no hire requests yet."
    return as_json(rows)


@server.tool()
@db_errors
def run_query(
    sql: Annotated[
        str,
        Field(
            description="A single read-only SQL SELECT statement. "
            "No semicolons, no INSERT/UPDATE/DELETE/DROP."
        ),
    ],
) -> str:
    """Last resort: run one read-only SELECT against the HR database for a
    question the other tools do not cover. Prefer the named tools above. Tables:
    hire_types(name, description, probation_months, notice_period_days,
    benefits_eligible) and hire_requests(id, status, name, role, location,
    created_on)."""
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        return "QUERY_REJECTED: empty statement."
    if ";" in statement:
        return "QUERY_REJECTED: send exactly one statement, with no semicolons."
    if statement.split(None, 1)[0].lower() not in {"select", "with"}:
        return "QUERY_REJECTED: only SELECT statements are allowed here."

    with connect() as conn:
        # Real enforcement: Postgres itself refuses writes in this session, so a
        # statement that slips past the checks above still cannot modify
        # anything. A rejected write comes back through @db_errors as DB_ERROR.
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(statement)  # type: ignore[arg-type]
            rows = cur.fetchmany(MAX_ROWS)

    if not rows:
        return "QUERY_OK: no rows matched."
    return as_json(rows)


if __name__ == "__main__":
    server.run(transport="stdio")
