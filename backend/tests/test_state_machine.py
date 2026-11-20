"""P3.6 table-driven tests of every transition in docs/02 §3."""

from __future__ import annotations

import pytest

from app.alerts.state_machine import AlertConfig, AssetHealth, State

CFG = AlertConfig()


def run(events: list[tuple]) -> tuple[AssetHealth, list[tuple[str, str]]]:
    h = AssetHealth(CFG)
    out = []
    for ev in events:
        kind, *args = ev
        t = getattr(h, f"on_{kind}")(*args)
        if t:
            out.append((t.from_state.value, t.to_state.value))
    return h, out


def P(rul: float, p10: float | None = None) -> tuple:
    return ("prediction", rul, rul - 10 if p10 is None else p10)


@pytest.mark.parametrize("events,final,transitions", [
    ([("message",)], "WARMING_UP", [("NEW", "WARMING_UP")]),
    ([("message",), P(100)], "HEALTHY", [("NEW", "WARMING_UP"), ("WARMING_UP", "HEALTHY")]),
    ([("message",), P(50)], "WARNING", [("NEW", "WARMING_UP"), ("WARMING_UP", "WARNING")]),
    ([("message",), P(20, 16)], "CRITICAL", [("NEW", "WARMING_UP"), ("WARMING_UP", "CRITICAL")]),
    # escalation needs 2 consecutive predictions
    ([("message",), P(100), P(70)], "HEALTHY", None),
    ([("message",), P(100), P(70), P(70)], "WARNING", None),
    ([("message",), P(100), P(70), P(90), P(70)], "HEALTHY", None),  # streak broken
    # healthy -> critical directly after 2 votes
    ([("message",), P(100), P(25, 20), P(25, 20)], "CRITICAL", None),
    # safety override: a single prediction with p10 <= 15
    ([("message",), P(100), P(60, 15)], "CRITICAL", None),
    # de-escalation needs 5 consecutive AND a 5-cycle margin
    ([("message",), P(50)] + [P(78)] * 5, "WARNING", None),  # 78 <= 75 + 5: no margin
    ([("message",), P(50)] + [P(81)] * 4, "WARNING", None),
    ([("message",), P(50)] + [P(81)] * 5, "HEALTHY", None),
    ([("message",), P(20, 16)] + [P(40)] * 5, "WARNING", None),
    ([("message",), P(20, 16)] + [P(100)] * 5, "HEALTHY", None),
    # offline and back to the previous state
    ([("message",), P(50), ("offline",)], "OFFLINE", None),
    ([("message",), P(50), ("offline",), ("message",)], "WARNING", None),
    ([("message",), ("offline",), ("message",)], "WARMING_UP", None),
    ([("offline",)], "NEW", []),  # never-seen assets do not go offline
    # degraded data after 3 consecutive bad messages, recovery after 3 good ones
    ([("message",), P(100), ("data_quality", True), ("data_quality", True)], "HEALTHY", None),
    ([("message",), P(100)] + [("data_quality", True)] * 3, "DEGRADED_DATA", None),
    ([("message",), P(100)] + [("data_quality", True)] * 3 + [P(10, 5)], "DEGRADED_DATA", None),  # frozen
    ([("message",), P(100)] + [("data_quality", True)] * 3 + [("data_quality", False)] * 3, "HEALTHY", None),
    ([("message",)] + [("data_quality", True)] * 3 + [("data_quality", False)] * 3, "WARMING_UP", None),
    # new life
    ([("message",), P(10, 5), ("new_life",)], "WARMING_UP", None),
])
def test_transitions(events, final, transitions):
    h, out = run(events)
    assert h.state.value == final
    if transitions is not None:
        assert out == transitions


def test_classify_boundaries():
    assert CFG.classify(75.0) == State.WARNING and CFG.classify(75.01) == State.HEALTHY
    assert CFG.classify(30.0) == State.CRITICAL and CFG.classify(30.01) == State.WARNING


def test_from_dict_ignores_unknown_keys():
    c = AlertConfig.from_dict({"warning_rul": 80, "rate_limit_per_asset": 50})
    assert c.warning_rul == 80 and c.critical_rul == 30
