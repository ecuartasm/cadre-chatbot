"""Load .env for the test session.

Without this, `os.getenv("ANTHROPIC_API_KEY")` is None during tests and every
`@pytest.mark.skipif(not os.getenv(...))` test SKIPS silently — including the live
`count_tokens` check, which is the one that actually verifies the cache floor against
reality rather than against a hard-coded constant. A skipped test that looks like a pass
is worse than no test.
"""

from dotenv import load_dotenv

load_dotenv()
