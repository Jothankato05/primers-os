import json
import os

import pytest

from core import benchmark as bm

ANALYZE = """Startup finished in 3.512s (firmware) + 1.204s (loader) + 2.150s (kernel) + 1min 2.5s (userspace) = 1min 9.366s
graphical.target reached after 8.977s in userspace
"""


@pytest.mark.parametrize("text, seconds", [
    ("2.150s", 2.15), ("567ms", 0.567), ("1min 2.5s", 62.5), ("1h 2min", 3720.0), ("850us", 0.00085), ("", None),
])
def test_parse_duration(text, seconds):
    assert bm.parse_duration(text) == seconds


def test_parse_analyze_and_boot_to_login():
    a = bm.parse_analyze(ANALYZE)
    assert a == {"firmware": 3.512, "loader": 1.204, "kernel": 2.15, "userspace": 62.5,
                 "total": 69.366, "graphical": 8.977}
    assert bm.boot_to_login(a) == pytest.approx(3.512 + 1.204 + 2.15 + 8.977)
    vm = bm.parse_analyze("Startup finished in 1.9s (kernel) + 3.1s (initrd) + 10.2s (userspace) = 15.2s\n")
    assert vm == {"kernel": 1.9, "initrd": 3.1, "userspace": 10.2, "total": 15.2}
    assert bm.boot_to_login(vm) == 15.2
    assert bm.parse_analyze("Bootup is not yet finished.") == {}


def test_parse_meminfo():
    mem = bm.parse_meminfo("MemTotal:  4028520 kB\nMemFree: 100 kB\nMemAvailable:  3480000 kB\n")
    assert mem == {"total_mb": 3934, "available_mb": 3398, "used_mb": 536}
    assert bm.parse_meminfo("") == {}


def test_root_device():
    info = ("25 1 8:2 / / rw,relatime shared:1 - ext4 /dev/sda2 rw\n"
            "30 25 0:5 / /dev rw - devtmpfs udev rw\n")
    assert bm.root_device(info) == "sda2"
    assert bm.root_device("1 0 0:1 / / rw - overlay overlay rw\n") is None


def test_is_rotational_follows_partitions_and_dm(tmp_path):
    blk = tmp_path / "block"
    dev = tmp_path / "devices"
    (dev / "sda" / "sda2").mkdir(parents=True)
    (dev / "sda" / "queue").mkdir()
    (dev / "sda" / "queue" / "rotational").write_text("1\n")
    (dev / "sda" / "sda2" / "partition").write_text("2\n")
    (dev / "nvme0n1" / "queue").mkdir(parents=True)
    (dev / "nvme0n1" / "queue" / "rotational").write_text("0\n")
    (dev / "dm-0" / "slaves").mkdir(parents=True)
    os.symlink(str(dev / "nvme0n1"), dev / "dm-0" / "slaves" / "nvme0n1")
    blk.mkdir()
    for name, target in (("sda", "sda"), ("sda2", "sda/sda2"), ("nvme0n1", "nvme0n1"), ("dm-0", "dm-0")):
        os.symlink(str(dev / target), blk / name)
    assert bm.is_rotational("sda2", str(blk)) is True
    assert bm.is_rotational("nvme0n1", str(blk)) is False
    assert bm.is_rotational("dm-0", str(blk)) is False
    assert bm.is_rotational("missing", str(blk)) is None
    assert bm.is_rotational(None, str(blk)) is None


def report(**over):
    r = {"live_session": False, "memory": {"total_mb": 3934, "used_mb": 536},
         "boot": {"to_login": 13.2}, "disk": {"rotational": False, "total_gb": 120.0, "used_gb": 6.1}}
    r.update(over)
    return r


def test_evaluate_against_targets():
    rows = {row[0]: row for row in bm.evaluate(report())}
    assert rows["RAM installed"][3] == "pass" and rows["RAM in use now"][3] == "pass"
    assert rows["Boot to login"][1:] == ("13.2 s", "< 15 s on SSD", "pass")
    assert rows["Disk size"][3] == "pass" and rows["Disk used"][3] == "pass"

    hdd = {row[0]: row for row in bm.evaluate(report(boot={"to_login": 22.0},
                                                     disk={"rotational": True, "total_gb": 500.0}))}
    assert hdd["Boot to login"][2:] == ("< 30 s on hard disk", "pass")

    slow = {row[0]: row for row in bm.evaluate(report(memory={"total_mb": 1024, "used_mb": 800},
                                                      boot={"to_login": 18.0}))}
    assert slow["RAM installed"][3] == "fail" and slow["RAM in use now"][3] == "fail"
    assert slow["Boot to login"][3] == "fail"

    live = {row[0]: row for row in bm.evaluate(report(live_session=True))}
    assert live["Boot to login"][3] == "n/a" and "Disk size" not in live


def test_collect_never_raises_and_save(tmp_path):
    r = bm.collect(run=lambda argv: ANALYZE)
    assert r["report"] == "primers-benchmark/1" and r["boot"]["graphical"] == 8.977
    path = bm.save(r, str(tmp_path / "bench"))
    data = json.load(open(path))
    assert data["results"] and {"check", "measured", "target", "result"} <= set(data["results"][0])
    text = json.dumps(data)
    assert os.environ.get("USER", "nobody-xyz") not in text.replace('"user', "")  # no user name in the report


def test_brain_benchmark_command(shell, capsys, monkeypatch):
    monkeypatch.setattr(bm, "collect", lambda: dict(report(), report="primers-benchmark/1", os="PRIMERS OS",
                                                    kernel="6.8", uptime_s=600, measured="now",
                                                    hardware={"cpu": "Intel i3", "cores": 4, "model": "OptiPlex 7010",
                                                              "vendor": "Dell"}))
    shell.execute("how fast does this pc boot?")
    out = capsys.readouterr().out
    assert "BENCHMARK" in out and "Boot to login" in out and "13.2 s" in out and "Saved:" in out
    shell.execute("benchmark --json")
    data = json.loads(capsys.readouterr().out)
    assert data["hardware"]["model"] == "OptiPlex 7010" and data["results"]
