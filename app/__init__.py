"""Package init — loads `.env` before anything else in `app.` can read the environment.

⚠️ **This exists to fix a real, silent bug, and moving it will bring the bug back.**

`load_dotenv()` used to live in `app/main.py`, after its imports. Python runs imports first, so
`from app.api.chat import ...` pulled in `app.llm.client`, which resolves
`MODEL = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)` at *its* module level — before `.env` had been
read. The result: setting `ANTHROPIC_MODEL=claude-sonnet-5` in `.env` did nothing at all. The app
kept running Haiku while the file said Sonnet, and every test passed.

It hid through an entire model-switch phase because the two paths agreed by coincidence: `.env` said
`claude-haiku-4-5` and `DEFAULT_MODEL` was also `claude-haiku-4-5`, so the fallback returned the
right answer for the wrong reason. Every Sonnet verification had used a shell variable
(`ANTHROPIC_MODEL=claude-sonnet-5 uvicorn ...`), which skips `.env` and therefore skips the bug.

`app/__init__.py` runs before any `app.*` module is imported, from *every* entry point — uvicorn,
pytest, `eval/golden.py`, `mcp_server/`, `scripts/`. That is why the load lives here rather than in
any one of them: there is no import order that can defeat it.

`override=False` is the dotenv default and is deliberate — a real environment variable (Railway's
dashboard, a CI secret, `ANTHROPIC_MODEL=... uvicorn`) still wins over the committed file.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()
