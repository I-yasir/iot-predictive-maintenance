from itertools import islice

from pdm_iot.simulator.replay import ReplayConfig, build_messages


def test_continuous_keeps_every_unit_active() -> None:
    cfg = ReplayConfig("FD001", "test", units=[1, 2], speed_cps=0, continuous=True)
    lens = {}
    ticks = list(islice(build_messages(cfg), 400))  # unit 1 has 31 cycles, unit 2 has 49
    assert all(len(t) == 2 for t in ticks)
    for t in ticks:
        for m in t:
            lens[m["meta"]["unit"]] = m["meta"]["len"]
    u1 = [m for t in ticks for m in t if m["meta"]["unit"] == 1]
    assert u1[lens[1]]["cycle"] == 1 and u1[lens[1] - 1]["meta"]["eol"]  # restarted as a new life
    assert len({m["msg_id"] for m in u1}) == len(u1)
