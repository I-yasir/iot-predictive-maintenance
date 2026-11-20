import json

from pdm_contracts import Accepted, load_profiles
from pdm_iot.simulator.replay import ReplayConfig, ReplaySimulator, ReplayState, asset_id_for, build_messages
from pdm_iot.transports import MemoryTransport
from pdm_ml.config import find_root
from pdm_ml.io.loader import load_split, load_true_rul


def test_asset_ids():
    assert asset_id_for("FD001", "test", 34) == "FD001-T034"
    assert asset_id_for("FD001", "train", 7) == "FD001-R007"


def test_unit_34_emits_every_row_in_order_and_validates():
    profiles = load_profiles(find_root() / "config" / "profiles")
    msgs = [m for tick in build_messages(ReplayConfig("FD001", units=[34], speed_cps=0)) for m in tick]
    rows = load_split("FD001", "test").query("unit == 34")
    assert len(msgs) == len(rows)
    assert [m["cycle"] for m in msgs] == rows.cycle.tolist()
    assert [m["seq"] for m in msgs] == list(range(1, len(rows) + 1))
    assert msgs[-1]["meta"]["true_rul"] == int(load_true_rul("FD001").loc[34])
    assert msgs[-1]["meta"]["eol"] and not msgs[0]["meta"]["eol"]
    assert abs(msgs[0]["sensors"]["T30"] - rows.T30.iloc[0]) < 1e-3
    for m in msgs:
        assert isinstance(__import__("pdm_contracts").validate_message(json.dumps(m), profiles), Accepted)


def test_round_robin_and_state_machine():
    t = MemoryTransport()
    sim = ReplaySimulator(ReplayConfig("FD001", units=[1, 2], speed_cps=0), t)
    sim.start(block=True)
    assert sim.state == ReplayState.COMPLETED
    first_two = [json.loads(b)["asset_id"] for b in t.sent[:2]]
    assert first_two == ["FD001-T001", "FD001-T002"]
    assert sim.stats.failed == 0 and sim.stats.sent == len(t.sent)


def test_three_consecutive_failures_set_error():
    from pdm_iot.transports import SendResult

    class Down(MemoryTransport):
        def send(self, payload, raw=None):
            return SendResult(False, "down")

    sim = ReplaySimulator(ReplayConfig("FD001", units=[1], speed_cps=0), Down())
    sim.start(block=True)
    assert sim.state == ReplayState.ERROR and sim.stats.sent == 3


def test_loop_laps_and_new_runs_get_fresh_msg_ids():
    """Ingest dedups on msg_id, so a looped lap must not reuse the previous lap's ids."""
    import time as _t

    t = MemoryTransport()
    sim = ReplaySimulator(ReplayConfig("FD001", units=[1], speed_cps=0, loop=True), t)
    sim.start()
    deadline = _t.time() + 10
    while len(t.sent) < 31 * 3 and _t.time() < deadline:  # unit 1 has 31 cycles
        _t.sleep(0.01)
    sim.stop()
    ids = [json.loads(b)["msg_id"] for b in t.sent]
    cycles = [json.loads(b)["cycle"] for b in t.sent]
    assert cycles.count(1) >= 3
    assert len(ids) == len(set(ids))

    t2 = MemoryTransport()
    ReplaySimulator(ReplayConfig("FD001", units=[1], speed_cps=0), t2).start(block=True)
    assert not set(ids) & {json.loads(b)["msg_id"] for b in t2.sent}
