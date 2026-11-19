# Project Connect learning materials

This repo holds the learning materials of the Project Connect team: the code team members build while learning new things, and the notes that explain it. Each piece is small, runnable and meant to be read by the next person who learns the same topic.

## What is in this repo

All work lives under `members/<your-name>/<topic>/`, one folder per topic.

| Folder | What it is |
| --- | --- |
| `members/santoosh/maf-implementation/` | A small Microsoft Agent Framework agent that answers HR questions about hire types, from the Local-MAF-agent repo |
| `members/santoosh/mcp-implementation/` | An agent that works with HR data in PostgreSQL through an MCP server, from the Agent-integration-with-database-via-MCP repo |

Add a row to this table when you add a topic.

## How to add your work

Work on your own branch and never push straight to `main`. These commands use PowerShell. On macOS or Linux, the Git commands are the same.

1. **Clone the repo** to a folder that OneDrive does not sync, such as `C:\Projects`. OneDrive can lock Git's files.

   ```powershell
   git clone https://github.com/Sunnytachyontech/Project-connect-learning-materials.git
   cd Project-connect-learning-materials
   ```

2. **Create a branch** from the latest `main`. Name it after your topic, for example `maf-implementation`. If that name is taken, add your name at the end.

   ```powershell
   git checkout main
   git pull
   git checkout -b <topic>-implementation
   ```

3. **Copy your project** into `members/<your-name>/<topic>/`, leaving out `.git`, `.env`, your virtual environment and caches.

   ```powershell
   robocopy <path-to-your-project> members\<your-name>\<topic> /E /XD .git .venv __pycache__ /XF .env *.bak
   ```

   On macOS or Linux:

   ```bash
   rsync -a --exclude .git --exclude .env --exclude .venv --exclude __pycache__ <path-to-your-project>/ members/<your-name>/<topic>/
   ```

4. **Add a README** inside your topic folder. Say what the project does, what you learned, how to set it up and how to run it.

5. **Check before you commit.** Only your own folder should be listed, and the search should show only placeholder values.

   ```powershell
   git add .
   git status
   git diff --cached | Select-String -Pattern "password|secret|api[_-]?key|token|postgresql://"
   ```

   On macOS or Linux, replace the last line with `git diff --cached | grep -iE "password|secret|api[_-]?key|token|postgresql://"`.

6. **Commit and push** your branch.

   ```powershell
   git commit -m "Add <topic> learning material"
   git push -u origin <topic>-implementation
   ```

7. **Open a pull request** into `main` on GitHub, add a reviewer, and wait for approval. The pull request is merged once the reviewer approves it.

## Rules for this repo

This repo is public, so everything you push can be read by anyone, including its history.

- Never commit `.env` files, API keys, passwords, tokens, or connection strings with real credentials.
- Provide a `.env.example` with placeholder values such as `change-me` so others know which settings they need.
- Use sample data only. No real candidate, employee or client data.
- Leave out client names, internal URLs, Jira keys and internal documents.
- Never push directly to `main`. Every change goes through a pull request.
- Keep one topic per branch and one folder per topic.

## Pull request checklist

- [ ] No `.env`, keys, passwords or real credentials
- [ ] `.env.example` has placeholders only
- [ ] The code sits under `members/<your-name>/<topic>/`
- [ ] The topic folder has a README with setup and run steps
- [ ] This README's table has a row for the new topic
