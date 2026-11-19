# Local MAF Agent

A Microsoft Agent Framework (MAF) agent that answers HR questions against a
local PostgreSQL database, reached over MCP.

```
agents/   multi_agent.py   The agent. Tools come from PostgreSQL over MCP.
server/   pg_mcp_server.py The MCP server. Owns the DB connection, exposes 5 tools.
core/     llm.py           OpenRouter client + provider-error messages.
          db.py            connect() -- PostgreSQL settings from .env.
          prompt.py        The agent's system prompt (the 12 rules).
scripts/  setup_db.py      Schema + reference data. The only version-controlled
                           definition of the database -- this rebuilds it.
          check_models.py  Proves a model really calls tools before you trust it.
docs/                      Notes and code reviews.
```

The agent reads **nothing** from the project folder. Hire types and hire
requests come from PostgreSQL; the model comes from OpenRouter; the only file
it needs is `.env`.

Entry points (`agents/`, `scripts/`, `server/`) each put the project root on
`sys.path` so `core.*` imports resolve when the file is run directly. That
keeps `python agents/multi_agent.py` working from any working directory.

The agent is instructed never to answer a hire-type question from memory.

The database is local; the model is not. The agent runs on a single
OpenRouter model -- see [Choosing a model](#choosing-a-model).

## Setup

```powershell
py -3.14 -m venv taketwo
.\taketwo\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env
```

Then add your OpenRouter key to `.env` -- see
[Choosing a model](#choosing-a-model).

### PostgreSQL (needed by `multi_agent.py` only)

Create the database and the role the agent connects as. Run this as a
superuser -- `psql` will prompt for the `postgres` password:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE ROLE hr_agent LOGIN PASSWORD 'choose-a-password';"
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE hr_demo OWNER hr_agent;"
```

Put that password in `.env` as `PGPASSWORD`, then create the tables and load
the hire types:

```powershell
python scripts/setup_db.py
```

Expected output:

```
Schema ready.
  hire_types:    4 rows
  hire_requests: 0 rows
```

`setup_db.py` is safe to re-run -- it creates tables only if missing and
upserts the hire types, so edits to the `HIRE_TYPES` list in that file flow
into the database.

## Run

```powershell
python agents/multi_agent.py

```

Then ask questions at the prompt, for example:

- `list out the hire types`
- `what is the notice period for Intern?`
- `raise a hire request for Asha` (the agent will ask for role and location)
- `what hire requests do we have so far?`

Type `/reset` for a fresh conversation, `exit` to quit.

The hire request will pause for a `y/N` approval showing the exact row to be
written. Ask for the same one twice and the second attempt comes back as
`DUPLICATE_HIRE_REQUEST` rather than creating a second row.

## How the MCP wiring works

`multi_agent.py` never imports `psycopg` and holds no connection string. It
spawns `pg_mcp_server.py` as a subprocess and speaks MCP to it over
stdin/stdout:

```
multi_agent.py                      pg_mcp_server.py
  MCPStdioTool  ──  stdio/MCP  ──►    MCPServer  ──►  PostgreSQL
  (client)                            (server)
```

On startup the client runs the MCP handshake, asks the server what tools it
has, and hands them to the `Agent` as if they were ordinary Python tools. You
should see this line before the first prompt:

```
MCP server connected: postgres_hr -> [create_hire_request, get_hire_type, list_hire_requests, list_hire_types, run_query]
```

If that list is empty or the line never prints, the server failed to start --
run `python server/pg_mcp_server.py` on its own to see the error.

The five tools:

| Tool | Does |
|---|---|
| `list_hire_types()` | All hire types. |
| `get_hire_type(name)` | One hire type, or `HIRE_TYPE_NOT_FOUND` with the valid names. |
| `create_hire_request(name, role, location)` | Writes a row. **Asks for human approval first.** Returns `MISSING_FIELDS` if any value is absent or a placeholder, or `DUPLICATE_HIRE_REQUEST` if it already exists. |
| `list_hire_requests()` | Saved requests, newest first. |
| `run_query(sql)` | Escape hatch for one read-only `SELECT`. |

### Guardrails live in the server, not the prompt

A prompt rule is advice; a server check is enforcement. `pg_mcp_server.py`
holds three:

- **No invented values.** `create_hire_request` rejects a missing or
  placeholder `name`/`role`/`location` with `MISSING_FIELDS` *before* touching
  the database, so a guessed row can never be written.
- **`run_query` is genuinely read-only.** It rejects anything that is not a
  single `SELECT`/`WITH`, *and* sets `conn.read_only = True` so Postgres itself
  refuses a write that slips past the string checks.
- **Database failures come back as text.** The `@db_errors` decorator turns an
  `OperationalError` into `DB_UNAVAILABLE: ...` instead of letting it escape as
  an MCP protocol error, which the model cannot explain to the user.

- **No duplicate requests.** The same person, role and location on the same day
  returns `DUPLICATE_HIRE_REQUEST` naming the existing id, and a unique index
  (`hire_requests_no_same_day_dupes`) blocks anything that bypasses the check.
  Matching is case- and whitespace-insensitive, so `asha rao` and `Asha Rao`
  are the same person. Scoping to `created_on` means a genuine re-hire for the
  same role months later still works.

## Human approval for writes

Reads run unattended. `create_hire_request` -- the only tool that writes --
stops and asks first:

```
  +-- APPROVAL REQUIRED ---------------------------------------
  |  tool: create_hire_request
  |  data to be written to the database:
  |      name     = 'Asha Rao'
  |      role     = 'Backend Engineer'
  |      location = 'Hyderabad'
  +------------------------------------------------------------
  Approve this write? [y/N]:
```

Anything other than `y`/`yes` rejects the call, and nothing is written.

The gate is declared per tool in `build_postgres_tool`:

```python
approval_mode=MCPSpecificApproval(
    always_require_approval=["create_hire_request"],
    default="never_require",
),
```

Set `default` explicitly -- omitting it emits a `FutureWarning`, because that
implicit fallback may change in a future release. Note that
`MCPSpecificApproval` is not re-exported at the top level in
agent-framework 1.25.0, so it is imported from `agent_framework._mcp`.

The flag alone is only half of it. A gated tool does not run; the framework
returns a `function_approval_request` carrying the exact call the model wanted
to make, and waits. `run_turn()` in `multi_agent.py` handles that round trip:
it pulls the requests out of the response, shows each one via `ask_human()`,
and sends the answers back as a user message built from
`to_function_approval_response()`. It loops rather than checking once, because
the model may call another gated tool after the first is answered.

This is also why the approval prompt can show the data: the pending call's
arguments are right there on the request, via `call.parse_arguments()`.

### Session memory vs. the database

`/reset` starts a new MAF session, so the agent forgets the conversation. It
does **not** empty the database -- `list_hire_requests()` still returns
everything saved before, including from previous runs. That split is the point
of the 3/7 exercise: conversation state is per-session, business data is not.

## Choosing a model

The agent runs on **one** OpenRouter model, set as `OPENROUTER_MODEL` in
`.env`. There is no fallback or rotation -- if that model is unavailable, the
run fails and you pick another one by hand.

`llm.py` is the only file that talks to OpenRouter. It is OpenAI-compatible,
so the stock Chat Completions client works once `base_url` points at it.

### Setup

1. Get a key at <https://openrouter.ai/keys>, put it in `.env` as
   `OPENROUTER_API_KEY`.
2. For a `:free` model, enable the prompt logging/training data policy at
   <https://openrouter.ai/settings/privacy>. Without it requests fail with a
   404 `No endpoints found matching your data policy` -- a confusing error
   that looks like a bad model id.
3. Verify the model before trusting it (below), then set `OPENROUTER_MODEL`.

### Rate limits

The free tier caps requests **per day, across every `:free` model on the
account** -- the error is `429 Rate limit exceeded: free-models-per-day`.
Switching `OPENROUTER_MODEL` to a different free model does **not** help: the
quota is shared. Either wait for the daily reset, or add credits at
<https://openrouter.ai/settings/credits> (10 credits unlocks 1000 free-model
requests per day, and also removes the data-policy requirement).

A few sweeps plus a handful of end-to-end runs is enough to exhaust a day's
free quota, so expect to hit this while developing.

`multi_agent.py` catches provider failures and prints one actionable line
instead of a traceback, keeping the session and the MCP server alive:

```
  [model unavailable] OpenRouter rate limit reached. The free tier caps
  requests per DAY across every :free model ...
```

`explain_model_error()` maps 429 / 401 / 404 to the setting that fixes each.
Note this is *operator* output -- naming OpenRouter and the config key is
helpful here. RULE 11 governs what the agent says to an HR user, and does not
apply to these messages.

### Verify tool calling first

**This is the single most important check.** The model must support tool
calling, or the agent silently never reaches the database -- it just makes
something up.

```powershell
python scripts/check_models.py                  # test OPENROUTER_MODEL from .env
python scripts/check_models.py <model-id> ...   # test others
```

It hands the model one tool and checks whether the function really executed,
reporting `PASS`, `NO TOOL CALL`, `CALLED, BAD ANSWER` or `ERROR`. Only a
`PASS` belongs in `.env`.

Models verified working at the time of writing -- all free, all tool-capable:

| Model | Note |
|---|---|
| `nvidia/nemotron-3-ultra-550b-a55b:free` | Current default |
| `nvidia/nemotron-3.5-lightning:free` | |
| `inclusionai/ling-3.2-flash:free` | |
| `baidu/ernie-5.5-flash-preview:free` | |

That roster churns, so re-running the check matters more than the list.

### Why this check exists

An earlier version of this project ran on Foundry Local, where `phi-4-mini` is
advertised with `supports_tool_calling=True` but writes the tool call out as
ordinary message text instead:

```
[{"name":"lookup_hire_type","parameters":{"properties":{"name":"all"}}}]
```

Note the `"properties"` wrapper -- the model is copying the JSON *schema* it
was shown instead of filling in an arguments object. The framework never
recognises this as a tool call, so the tool never runs and that raw string is
returned as the answer.

The lesson generalises to any provider: treat a catalogue's "supports tools"
flag as necessary but not sufficient, and prove it.

## Performance

Expect seconds per turn. A turn that writes to the database makes several
round trips -- the model calls the tool, you approve, the model reads the
result and replies -- so it is not instant.

This project previously ran on Foundry Local, which ships only `generic-cpu`
builds and took a minute or more per response on a machine with no discrete
GPU. That is why it moved to OpenRouter. Ollama was considered as an
alternative and rejected for the same reason: it is local inference on the
same CPU, so it would not have been faster.
