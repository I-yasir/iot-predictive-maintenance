import json
import shutil
import subprocess

import pytest

from pdm_contracts import Accepted, Rejection, load_profiles, validate_message
from pdm_iot.simulator.virtual_esp32 import (
    DISTRIBUTION,
    TRAJECTORY,
    Generator,
    VirtualDevice,
    load_profile_json,
    parse_faults,
    run,
)
from pdm_iot.transports import MemoryTransport
from pdm_ml.config import find_root

ROOT = find_root()
PROFILES = load_profiles(ROOT / "config" / "profiles")


def test_trajectory_follows_unit_34():
    prof = load_profile_json()
    g = Generator(prof, 12345, TRAJECTORY)
    assert g.life == len(prof["trajectory"]) == 203
    cyc, v = g.next()
    assert cyc == 1
    assert v[:3] == pytest.approx(prof["trajectory"][0][:3], abs=1e-4)  # settings carry no noise
    assert g.true_remaining() == 202 + prof["trajectory_true_rul_end"]


def test_distribution_life_and_restart():
    g = Generator(load_profile_json(), 7, DISTRIBUTION)
    life = g.life
    assert life >= load_profile_json()["life_min"]
    for _ in range(life):
        g.next()
    assert g.end_of_life
    cyc, _ = g.next()
    assert cyc == 1


@pytest.mark.parametrize("mode", [TRAJECTORY, DISTRIBUTION])
def test_clean_payloads_validate(mode):
    dev = VirtualDevice("FD001-V001", mode=mode)
    for _ in range(250):
        res = validate_message(json.dumps(dev.next_payload()), PROFILES, ("lab", "FD001-V001"))
        assert isinstance(res, Accepted), res


def test_faults_produce_expected_rejections():
    dev = VirtualDevice("FD001-V001", faults=parse_faults("malformed@2,missing@3,range@4,duplicate@5,out_of_order@6"))
    t = MemoryTransport()
    stats = run(dev, t, 7, 0)
    reasons = [r.reason if isinstance(r, Rejection) else "ok" for r in (validate_message(b, PROFILES) for b in t.sent)]
    assert reasons == ["ok", "parse_error", "schema:sensors.T30", "range:T30", "ok", "ok", "ok", "ok", "ok"]
    assert [f["kind"] for f in stats["injected"]] == ["malformed", "missing", "range", "duplicate", "out_of_order"]


def test_drop_buffers_and_flushes_in_order():
    dev = VirtualDevice("FD001-V001", faults=parse_faults("drop@3:4"))
    t = MemoryTransport()
    stats = run(dev, t, 10, 0)
    seqs = [json.loads(b)["seq"] for b in t.sent]
    assert seqs == list(range(1, 11)) and stats["buffer_overflow"] == 0


def test_bad_fault_spec():
    with pytest.raises(ValueError):
        parse_faults("explode@3")


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not installed")
@pytest.mark.parametrize("mode,flag", [(TRAJECTORY, "0"), (DISTRIBUTION, "1")])
def test_python_matches_cpp_generator(tmp_path, mode, flag):
    """The firmware generator and its Python twin must produce identical numbers for the same seed."""
    exe = tmp_path / "gen"
    src = ROOT / "iot" / "esp32" / "test" / "host_generator_test.cpp"
    subprocess.run(["g++", "-std=c++17", "-O2", "-I", str(ROOT / "iot" / "esp32" / "include"), str(src), "-o", str(exe)],
                   check=True)
    out = subprocess.run([str(exe), "12345", flag, "300"], check=True, capture_output=True, text=True).stdout.split("\n")
    g = Generator(load_profile_json(), 12345, mode)
    for line in filter(None, out):
        cyc, life, remaining, *vals = line.split(",")
        c, v = g.next()
        assert (int(cyc), int(life), int(remaining)) == (c, g.life, g.true_remaining())
        assert [float(x) for x in vals] == pytest.approx(v, abs=1e-9)
