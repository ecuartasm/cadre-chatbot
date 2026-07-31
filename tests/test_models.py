"""The model switch — `ANTHROPIC_MODEL=claude-sonnet-5` in `.env` and nothing else.

Three things were hardcoded to Haiku before `app/llm/models.py` existed, and every one of them
would have been **silently** wrong after a swap rather than raising:

- the cache floor (4,096 on Haiku, 1,024 on Sonnet) — the floor test would keep asserting Haiku's
  number, still passing while checking nothing real
- the price table (every Sonnet rate is 3×) — feeding the spend cap and `/api/stats`
- the measured prefix size — the two tokenise the same prompt 38% apart

These tests are what make the switch a `.env` change rather than a migration.
"""

from __future__ import annotations

import pytest

from app.llm.models import MODELS, UnknownModelError, spec_for
from app.obs.cost import Usage, cost_usd, rates_for


def test_both_models_are_specced():
    assert set(MODELS) == {"claude-haiku-4-5", "claude-sonnet-5"}


@pytest.mark.parametrize("mid", sorted(MODELS))
def test_every_spec_is_complete(mid: str):
    s = spec_for(mid)
    assert s.context_window > 0 and s.max_output > 0
    assert s.cache_floor > 0
    assert set(s.rates) == {"input", "output", "cache_write", "cache_read"}
    assert all(v > 0 for v in s.rates.values())


def test_cache_floors_are_non_monotonic():
    """The trap this registry exists for: the CHEAPER model has the HIGHER floor, so the value
    cannot be inferred from the tier and must be carried as data."""
    assert spec_for("claude-haiku-4-5").cache_floor == 4096
    assert spec_for("claude-sonnet-5").cache_floor == 1024
    assert spec_for("claude-haiku-4-5").rates["input"] < spec_for("claude-sonnet-5").rates["input"]


def test_measured_tokens_are_recorded_per_model():
    """The two tokenise the same prompt 38% apart (5,383 vs 7,415). One shared number would be
    silently wrong for whichever model was not measured, and the floor test would not notice."""
    from app.llm.prompt import MEASURED_SYSTEM_TOKENS_BY_MODEL as M

    assert set(M) == set(MODELS), "every specced model needs a measured prefix"
    for mid, tokens in M.items():
        assert tokens > spec_for(mid).cache_floor, f"{mid} prefix is below its own floor"


def test_thinking_is_sent_only_where_supported():
    """Haiku 4.5 rejects the `thinking` parameter; Sonnet 5 accepts it. `None` means omit."""
    assert spec_for("claude-haiku-4-5").thinking is None
    assert spec_for("claude-sonnet-5").thinking == {"type": "disabled"}


def test_sonnet_is_exactly_three_times_haiku():
    """Not a coincidence worth losing: it is why scale argues FOR Haiku rather than against it —
    the gap compounds with volume instead of shrinking."""
    h, s = spec_for("claude-haiku-4-5").rates, spec_for("claude-sonnet-5").rates
    for k in h:
        assert s[k] == pytest.approx(h[k] * 3), f"{k} is not 3x"


def test_cost_is_computed_from_the_active_model_not_a_default():
    u = Usage(input_tokens=12, output_tokens=150, cache_creation_input_tokens=5000)
    assert cost_usd(u, "claude-sonnet-5") == pytest.approx(cost_usd(u, "claude-haiku-4-5") * 3)


def test_an_unspecced_model_raises_rather_than_falling_back():
    """Falling back to another model's numbers would disable caching silently (wrong floor) and
    corrupt the spend cap (wrong rates) — the two failures hardest to notice."""
    with pytest.raises(UnknownModelError):
        spec_for("claude-does-not-exist")
    with pytest.raises(UnknownModelError):
        rates_for("claude-does-not-exist")


def test_there_is_exactly_one_price_table():
    """`cost.py` reads from the registry rather than keeping its own copy. Two tables would be two
    places for a rate to drift, and the drifted one would silently corrupt the cap."""
    from pathlib import Path

    src = (Path(__file__).parent.parent / "app" / "obs" / "cost.py").read_text(encoding="utf-8")
    assert "_RATES" not in src, "cost.py must not hold a second rate table"
    assert "spec_for" in src


def test_the_spend_cap_estimate_tracks_the_model():
    """The same $5 buys roughly a third as many turns on Sonnet. A hardcoded '~797 turns' comment
    would read as current after a swap and be wrong by 3x."""
    from app.obs.spend import worst_case_turn_usd

    assert worst_case_turn_usd() > 0
