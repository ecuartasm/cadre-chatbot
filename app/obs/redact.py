"""PII redaction — a pure function, deliberately not an inline regex at the call site.

Every user message is written to disk, and this bot's own subject matter includes Cadre's
data-security posture (scenario 5b). Its logging must not be the counterexample a
security-literate prospect would notice. Being a testable function rather than a `re.sub` buried
in a handler is the difference between a claim and a guarantee.

Scope, stated honestly: this catches the patterns people actually paste into a support chat —
email addresses, phone numbers, long digit runs that look like account or card numbers. It is
**not** a general PII classifier, and it will not catch a name or a street address. Retention is
the other half of the control (7 days, enforced by the rotation config), and the two are meant to
work together."""

from __future__ import annotations

import re

# Order matters: email before phone, or the digits inside an address-like local part get mangled
# first.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Emails
    (re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[email]"),
    # Long digit runs — card/account shaped (13+ digits, optional separators)
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[number]"),
    # Phone numbers: optional +, then 7–15 digits with common separators
    (re.compile(r"(?<![\w.])\+?\d[\d\s().-]{6,18}\d(?![\w.])"), "[phone]"),
)


def redact(text: str, *, max_chars: int = 2000) -> str:
    """Return `text` with obvious PII replaced by placeholders, truncated to `max_chars`.

    Truncation is part of the control, not a convenience: an unbounded field lets a caller write
    arbitrary volume into the log by pasting into the chat box.
    """
    if not text:
        return ""
    out = text
    for pattern, placeholder in _PATTERNS:
        out = pattern.sub(placeholder, out)
    if len(out) > max_chars:
        out = out[:max_chars] + f"…[truncated {len(out) - max_chars} chars]"
    return out
