"""One-time database setup: create the HR tables and seed hire types.

This file is the only version-controlled definition of the schema. The tables
otherwise exist only inside the live database, which is not in git -- so this
is what rebuilds hr_demo after a reinstall, a dropped database, or a fresh
clone. It is not a leftover script.

Reads the same .env settings as the MCP server, so if this connects the server
will too -- run it first to prove your credentials work.

    python scripts/setup_db.py

Safe to re-run: tables are created only if missing, and the hire types below
are upserted, so edits here flow into the database.
"""

import sys
from pathlib import Path

# Entry point: project root on sys.path before importing `core`.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.db import connect  # noqa: E402

# Reference data. Edit here and re-run to update the database; the UPSERT below
# makes that idempotent. The running agent never reads this -- it reads the
# hire_types table.
HIRE_TYPES = [
    {
        "name": "Full-time",
        "description": "Permanent employee on the company payroll.",
        "probation_months": 6,
        "notice_period_days": 60,
        "benefits_eligible": True,
    },
    {
        "name": "Contract",
        "description": "Fixed-term engagement with a defined end date.",
        "probation_months": 0,
        "notice_period_days": 15,
        "benefits_eligible": False,
    },
    {
        "name": "Intern",
        "description": "Short-term learning role, usually 3 to 6 months.",
        "probation_months": 0,
        "notice_period_days": 7,
        "benefits_eligible": False,
    },
    {
        "name": "Contract-to-Hire",
        "description": "Starts as a contract and can convert to full-time after review.",
        "probation_months": 3,
        "notice_period_days": 30,
        "benefits_eligible": False,
    },
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS hire_types (
    name               text    PRIMARY KEY,
    description        text    NOT NULL,
    probation_months   integer NOT NULL,
    notice_period_days integer NOT NULL,
    benefits_eligible  boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS hire_requests (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status      text        NOT NULL DEFAULT 'DRAFT',
    name        text        NOT NULL,
    role        text        NOT NULL,
    location    text        NOT NULL,
    created_on  date        NOT NULL DEFAULT current_date,
    created_at  timestamptz NOT NULL DEFAULT now()
);
"""

UPSERT = """
INSERT INTO hire_types
    (name, description, probation_months, notice_period_days, benefits_eligible)
VALUES (%(name)s, %(description)s, %(probation_months)s,
        %(notice_period_days)s, %(benefits_eligible)s)
ON CONFLICT (name) DO UPDATE SET
    description        = EXCLUDED.description,
    probation_months   = EXCLUDED.probation_months,
    notice_period_days = EXCLUDED.notice_period_days,
    benefits_eligible  = EXCLUDED.benefits_eligible
"""


def main() -> None:
    with connect()  as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)
        cur.executemany(UPSERT, HIRE_TYPES)
        conn.commit()

        cur.execute("SELECT count(*) AS n FROM hire_types")
        types_count = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM hire_requests")
        requests_count = cur.fetchone()["n"]

    print("Schema ready.")
    print(f"  hire_types:    {types_count} rows")
    print(f"  hire_requests: {requests_count} rows")


if __name__ == "__main__":
    main()
