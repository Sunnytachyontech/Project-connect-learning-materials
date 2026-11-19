"""PostgreSQL connection settings, shared by the MCP server and setup script.

Lives here rather than in the MCP server so `scripts/setup_db.py` can open a
connection without importing -- and therefore executing -- the whole server
module and its tool registrations.
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]

# Resolved against the project root: the MCP server is launched as a subprocess
# from an arbitrary working directory, so a relative .env would not be found.
load_dotenv(ROOT / ".env")


def connect() -> psycopg.Connection:
    """Open a fresh connection. One per tool call -- simple, and avoids holding
    a connection open while the model thinks."""
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "hr_demo"),
        user=os.getenv("PGUSER", "hr_agent"),
        password=os.getenv("PGPASSWORD", ""),
        row_factory=dict_row,
    )
