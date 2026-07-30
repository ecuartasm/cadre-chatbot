"""Log sink — decides *where* logs go, and refuses to lie about it.

The one job of this module is to make an unwritable log destination **loud**. On Railway the
volume mounts at runtime, shadows the image path, and arrives owned by root, so the app can easily
end up unable to write its own logs. Python's logging handlers swallow I/O errors by design
(`logging.raiseExceptions` only prints to stderr), so the natural symptom is an empty directory
that nobody notices for days.

Two modes, chosen explicitly rather than by accident:

- **`disk`** — the volume is mounted and writable. Logs go to stdout *and* rotating JSONL on disk.
- **`stdout-only`** — no volume (local dev, or a container without one). Logs go to stdout alone.

The distinction is reported by `/health`, so "are my logs actually persisting?" is answerable
without a shell. What is *not* allowed is silently believing we are in `disk` mode when we are
not."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Set only when the app is expected to persist logs. On Railway this points at the mounted volume.
LOG_DIR_ENV = os.getenv("LOG_DIR", "").strip()
RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "7"))

# In production an unwritable LOG_DIR is a deploy failure, not a warning. Locally it is normal to
# have no volume, so a missing LOG_DIR is fine — but a LOG_DIR that is *set and broken* never is.
STRICT = os.getenv("ENVIRONMENT", "development") == "production"


class LogSinkError(RuntimeError):
    """LOG_DIR was configured but cannot be written. Never downgrade this to a warning."""


@dataclass(frozen=True)
class SinkStatus:
    mode: str  # 'disk' | 'stdout-only'
    log_dir: str | None
    writable: bool
    retention_days: int
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "log_dir": self.log_dir,
            "writable": self.writable,
            "retention_days": self.retention_days,
            "detail": self.detail,
        }


def _probe(path: Path) -> tuple[bool, str]:
    """Actually write a file. `os.access` lies under containers, mounts, and root-squash NFS —
    the only trustworthy check is performing the operation we intend to perform."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, "verified by writing and removing a probe file"
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"


def resolve_sink() -> SinkStatus:
    if not LOG_DIR_ENV:
        return SinkStatus(
            mode="stdout-only",
            log_dir=None,
            writable=False,
            retention_days=RETENTION_DAYS,
            detail="LOG_DIR unset — stdout only (expected in local development)",
        )

    path = Path(LOG_DIR_ENV)
    ok, detail = _probe(path)

    if ok:
        return SinkStatus("disk", str(path), True, RETENTION_DAYS, detail)

    # LOG_DIR was configured and is not writable. In production that means the volume is missing,
    # mounted elsewhere, or still root-owned — every one of which loses the logs.
    msg = (
        f"LOG_DIR={path} is configured but not writable ({detail}). "
        "On Railway: confirm a volume is attached at this exact mount path and that "
        "docker-entrypoint.sh chowned it to uid 10001 before dropping privileges."
    )
    if STRICT:
        raise LogSinkError(msg)

    return SinkStatus("stdout-only", str(path), False, RETENTION_DAYS, f"NOT WRITABLE — {detail}")


# Resolved once at import, like the corpus loader — and for the same reason: a startup failure is
# visible in the deploy log, whereas a per-request failure is a slow leak.
SINK: SinkStatus = resolve_sink()
