"""primers-fleet: pairing, mutual TLS with pinned certificates, the command
allowlist and the log, over real sockets on this machine."""

import hashlib
import json
import os
import socket
import ssl
import stat
import subprocess
import threading

import pytest

from core import fleet


def paths(tmp_path, name):
    return fleet.FleetPaths(str(tmp_path / name), str(tmp_path / f"{name}.log"))


def events(p):
    try:
        with open(p.log) as f:
            return [json.loads(line) for line in f]
    except FileNotFoundError:
        return []


def wait_for(check, seconds=5.0):
    """The other side logs in its own thread: give it a moment."""
    import time
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def pairing(tmp_path):
    """An open pairing on the controller; yields (controller paths, code, port)."""
    ctrl = paths(tmp_path, "controller")
    code = fleet.new_code()
    p = fleet.Pairing(ctrl, code, port=0, host="127.0.0.1")
    t = threading.Thread(target=p.serve, args=(30,), daemon=True)
    t.start()
    yield ctrl, code, p.sock.getsockname()[1], p
    p.close()
    t.join(5)


class FakeRun:
    def __init__(self, rc=0, out="Exam Mode is on\n"):
        self.calls, self.rc, self.out = [], rc, out

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.rc, self.out, "" if self.rc == 0 else "refused\n")


@pytest.fixture
def paired(tmp_path, pairing):
    """A controller and a lab PC paired with it, the lab PC's agent running."""
    ctrl, code, port, _ = pairing
    lab = paths(tmp_path, "lab")
    fleet.join(lab, "127.0.0.1", code, port=port, name="Lab PC 01")
    exam_log = tmp_path / "exam.jsonl"
    exam_log.write_text('{"message": "exam started"}\n{"message": "visited https://cbt/"}\n')
    run = FakeRun()
    agent = fleet.Agent(lab, port=0, host="127.0.0.1", run=run, exam_log=str(exam_log),
                        status=lambda: {"name": "lab-pc-01", "lab": True, "exam": False, "candidate": False})
    threading.Thread(target=agent.serve_forever, daemon=True).start()
    pc = fleet.load_pcs(ctrl)[0]
    pc.port = agent.address[1]
    fleet.save_pc(ctrl, pc)
    yield ctrl, lab, pc, agent, run
    agent.stop()


# ---------------- identity and codes ----------------

def test_identity_is_made_once_and_its_key_is_private(tmp_path):
    p = paths(tmp_path, "pc")
    pem = fleet.ensure_identity(p, "lab-07")
    assert fleet.ensure_identity(p) == pem
    assert stat.S_IMODE(os.stat(p.key).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(p.key)).st_mode) == 0o700
    fp = fleet.fingerprint(pem)
    assert len(fp.split("-")) == 8 and all(len(g) == 4 for g in fp.split("-"))


def test_codes_are_long_unambiguous_and_typed_forgivingly():
    code = fleet.new_code()
    assert len(code) == 14 and code.count("-") == 2
    assert not set(code.replace("-", "")) & set("01OIL")
    assert fleet.normalise_code(code.lower().replace("-", " ")) == code.replace("-", "")
    for bad in ("", "1234-5678-9ABC", "ABCD-EFGH", "ABCD-EFGH-JKMN-P"):
        with pytest.raises(fleet.FleetError):
            fleet.normalise_code(bad)


# ---------------- pairing ----------------

def test_pairing_stores_each_side_and_logs_it(tmp_path, pairing):
    ctrl, code, port, _ = pairing
    lab = paths(tmp_path, "lab")
    fp = fleet.join(lab, "127.0.0.1", code, port=port, name="Lab PC 01")
    assert fp == fleet.fingerprint(fleet.ensure_identity(ctrl))
    assert list(fleet.controllers(lab)) == [fp]
    (pc,) = fleet.load_pcs(ctrl)
    assert pc.name == "lab-pc-01" and pc.address == "127.0.0.1"
    assert pc.cert == fleet.ensure_identity(lab)
    assert stat.S_IMODE(os.stat(os.path.join(ctrl.pcs, "lab-pc-01.json")).st_mode) == 0o600
    assert [e["event"] for e in events(ctrl)] == ["paired"]
    assert [e["event"] for e in events(lab)] == ["joined"]
    assert fleet.controller_addresses(lab) == ["127.0.0.1"]       # for the firewall rule


def test_same_names_are_told_apart_and_a_pc_pairing_again_is_updated(tmp_path, pairing):
    ctrl, code, port, _ = pairing
    a, b = paths(tmp_path, "a"), paths(tmp_path, "b")
    fleet.join(a, "127.0.0.1", code, port=port, name="primers-os")
    fleet.join(b, "127.0.0.1", code, port=port, name="primers-os")
    fleet.join(a, "127.0.0.1", code, port=port, name="primers-os")
    assert sorted(pc.name for pc in fleet.load_pcs(ctrl)) == ["primers-os", "primers-os-2"]


def test_a_wrong_code_pairs_nothing_on_either_side(tmp_path, pairing):
    ctrl, code, port, _ = pairing
    lab = paths(tmp_path, "lab")
    with pytest.raises(fleet.FleetError, match="doesn't know this code"):
        fleet.join(lab, "127.0.0.1", fleet.new_code(), port=port)
    assert fleet.controllers(lab) == {} and fleet.load_pcs(ctrl) == []
    assert wait_for(lambda: events(ctrl) and events(ctrl)[-1]["event"] == "pairing refused")


def test_pairing_closes_after_repeated_wrong_codes(tmp_path, pairing):
    ctrl, code, port, p = pairing
    lab = paths(tmp_path, "intruder")
    mine = fleet.ensure_identity(lab)
    for _ in range(fleet.MAX_PAIR_FAILURES):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            fleet._send(s, {"type": "join", "name": "x", "cert": mine, "nonce": "0" * 32})
            assert fleet._recv(s)["type"] == "challenge"
            fleet._send(s, {"type": "confirm", "mac": "0" * 64})       # can't compute it without the code
            assert fleet._recv(s)["type"] == "refused"
    assert p.closed.wait(5)
    assert fleet.load_pcs(ctrl) == []


def test_an_impostor_controller_without_the_code_is_refused_by_the_lab_pc(tmp_path):
    """Someone opens 'pairing' with their own code: the lab PC's code doesn't match theirs."""
    rogue = paths(tmp_path, "rogue")
    p = fleet.Pairing(rogue, fleet.new_code(), port=0, host="127.0.0.1")
    t = threading.Thread(target=p.serve, args=(10,), daemon=True)
    t.start()
    lab = paths(tmp_path, "lab")
    with pytest.raises(fleet.FleetError):
        fleet.join(lab, "127.0.0.1", fleet.new_code(), port=p.sock.getsockname()[1])
    p.close()
    t.join(5)
    assert fleet.controllers(lab) == {}


# ---------------- commands ----------------

def test_status_start_stop_and_the_log_on_both_sides(paired):
    ctrl, lab, pc, agent, run = paired
    assert fleet.call(ctrl, pc, "status")["status"]["lab"] is True
    r = fleet.call(ctrl, pc, "exam-start", {"url": "https://cbt.uni.edu.ng/", "allow": ["cdn.jsdelivr.net"]})
    assert r["ok"] and run.calls[-1] == ["primers-exam", "start", "https://cbt.uni.edu.ng/",
                                         "--allow", "cdn.jsdelivr.net"]
    assert fleet.call(ctrl, pc, "exam-stop")["ok"] and run.calls[-1] == ["primers-exam", "stop"]
    ctrl_fp = fleet.fingerprint(fleet.ensure_identity(ctrl))
    done = [e for e in events(lab) if e["event"] == "command"]
    assert [e["cmd"] for e in done] == ["status", "exam-start", "exam-stop"]
    assert all(e["by"] == ctrl_fp for e in done)
    assert done[1]["args"] == {"url": "https://cbt.uni.edu.ng/", "allow": ["cdn.jsdelivr.net"]}
    assert [e["cmd"] for e in events(ctrl) if e["event"] == "sent"] == ["status", "exam-start", "exam-stop"]


def test_a_failed_exam_start_is_reported(paired):
    ctrl, lab, pc, agent, run = paired
    run.rc = 1
    r = fleet.call(ctrl, pc, "exam-start", {"url": "https://cbt.uni.edu.ng/"})
    assert not r["ok"] and "refused" in r["error"]


@pytest.mark.parametrize("args", [{"url": "file:///etc/shadow"}, {"url": "javascript:alert(1)"},
                                  {"url": "https://x/", "allow": ["--all"]}, {"url": "https://x/", "allow": "x"},
                                  {"url": 7}])
def test_bad_arguments_never_reach_primers_exam(paired, args):
    ctrl, lab, pc, agent, run = paired
    assert not fleet.call(ctrl, pc, "exam-start", args)["ok"]
    assert run.calls == []


def test_only_the_listed_commands_run(paired):
    ctrl, lab, pc, agent, run = paired
    with pytest.raises(fleet.FleetError):
        fleet.call(ctrl, pc, "shell", {"cmd": "id"})
    # Sent anyway, by hand over the paired connection
    ctx = fleet._context(ssl.Purpose.SERVER_AUTH, ctrl, [pc.cert])
    with socket.create_connection((pc.address, pc.port)) as raw, ctx.wrap_socket(raw) as tls:
        fleet._send(tls, {"cmd": "shell", "args": {"cmd": "id"}})
        assert fleet._recv(tls) == {"ok": False, "error": "unknown command 'shell'"}
    assert run.calls == []
    assert wait_for(lambda: events(lab)[-1]["event"] == "command refused")


def test_collect_copies_each_log_with_checksums(paired, tmp_path):
    ctrl, lab, pc, agent, run = paired
    dest = tmp_path / "logs"
    results = fleet.collect(ctrl, [pc], str(dest))
    assert results[pc.name]["ok"]
    data = (dest / pc.name / "exam.jsonl").read_bytes()
    assert b"visited https://cbt/" in data
    assert (dest / "SHA256SUMS").read_text() == f"{hashlib.sha256(data).hexdigest()}  {pc.name}/exam.jsonl\n"


# ---------------- who may talk to whom ----------------

def test_a_controller_that_isnt_paired_is_refused_and_logged(paired, tmp_path):
    ctrl, lab, pc, agent, run = paired
    rogue = paths(tmp_path, "rogue")
    fleet.ensure_identity(rogue)
    r = fleet.call(rogue, pc, "exam-stop")
    assert not r["ok"] and r["error"].startswith("refused")
    assert run.calls == []
    assert wait_for(lambda: events(lab)[-1]["event"] == "refused")


def test_a_pc_that_left_cant_be_controlled(paired):
    ctrl, lab, pc, agent, run = paired
    assert fleet.forget_controllers(lab) == 1
    r = fleet.call(ctrl, pc, "status")
    assert not r["ok"]
    assert wait_for(lambda: "isn't paired" in events(lab)[-1].get("reason", ""))


def test_a_pc_that_isnt_paired_cant_be_controlled(tmp_path):
    lone = paths(tmp_path, "lone")
    agent = fleet.Agent(lone, port=0, host="127.0.0.1", run=FakeRun())
    threading.Thread(target=agent.serve_forever, daemon=True).start()
    ctrl = paths(tmp_path, "ctrl")
    fleet.ensure_identity(ctrl)
    pc = fleet.PC("lone", "127.0.0.1", agent.address[1], fleet.ensure_identity(lone))
    assert not fleet.call(ctrl, pc, "status")["ok"]
    agent.stop()


def test_the_controller_checks_it_reached_the_paired_pc(paired, tmp_path):
    """Another machine answering at the lab PC's address can't pretend to be it."""
    ctrl, lab, pc, agent, run = paired
    impostor = paths(tmp_path, "impostor")
    fleet.ensure_identity(impostor)
    for fp, pem in fleet.controllers(lab).items():
        fleet.trust_controller(impostor, pem)                   # it even trusts our controller
    fake = fleet.Agent(impostor, port=0, host="127.0.0.1", run=FakeRun())
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    moved = fleet.PC(pc.name, "127.0.0.1", fake.address[1], pc.cert)
    r = fleet.call(ctrl, moved, "status")
    assert not r["ok"] and "refused" in r["error"]
    fake.stop()


def test_tls_1_2_is_refused(paired):
    ctrl, lab, pc, agent, run = paired
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(ctrl.cert, ctrl.key)
    with socket.create_connection((pc.address, pc.port)) as raw:
        with pytest.raises(ssl.SSLError):
            ctx.wrap_socket(raw).do_handshake()


# ---------------- output and command line ----------------

def test_status_table():
    pcs = [fleet.PC("lab-01", "10.0.0.11", 7480, ""), fleet.PC("lab-02", "10.0.0.12", 7480, "")]
    text = fleet.format_status({"lab-01": {"ok": True, "status": {"lab": True, "exam": True, "candidate": True,
                                                                  "exam_url": "https://cbt/",
                                                                  "last_event": "visited https://cbt/q1"}},
                                "lab-02": {"ok": False, "error": "not reachable: timed out"}}, pcs)
    lines = text.splitlines()
    assert lines[0].split() == ["PC", "ADDRESS", "STATE", "LAB", "EXAM", "CANDIDATE", "LAST", "EVENT"]
    assert "on https://cbt/" in lines[1] and "signed in" in lines[1]
    assert "unreachable" in lines[2] and "timed out" in lines[2]


def test_cli_needs_root(monkeypatch, capsys):
    import primers_fleet
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert primers_fleet.main(["list"]) == 1
    assert "sudo" in capsys.readouterr().err


def test_agent_unit_runs_only_on_a_paired_pc():
    unit = open(os.path.join(os.path.dirname(__file__), "..", "..", "primers-distro", "overlays", "etc",
                             "systemd", "system", "primers-fleet-agent.service")).read()
    assert "ConditionDirectoryNotEmpty=/etc/primers/fleet/controllers" in unit
    assert "ExecStart=/usr/bin/primers-fleet agent" in unit
    assert "Wants=network-online.target" not in unit       # no boot-time wait for the network (benchmarks)


def test_join_opens_the_firewall_to_the_invigilator_pc_only_and_leave_closes_it(tmp_path, monkeypatch):
    import primers_fleet
    lab = paths(tmp_path, "lab")
    ctrl = paths(tmp_path, "ctrl")
    monkeypatch.setattr(fleet, "FleetPaths", lambda: lab)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(fleet, "join", lambda p, host, code: fleet.trust_controller(
        p, fleet.ensure_identity(ctrl), "192.168.77.10"))
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "Status: active\n" if argv[:2] == ["ufw", "status"] else "", "")
    monkeypatch.setattr(primers_fleet.subprocess, "run", run)
    assert primers_fleet.main(["join", "invigilator", "4KQ7-M2XD-9PTA"]) == 0
    rule = ["from", "192.168.77.10", "to", "any", "port", "7480", "proto", "tcp"]
    assert ["ufw", "allow", *rule] in calls
    assert ["systemctl", "enable", "--now", "primers-fleet-agent.service"] in calls
    calls.clear()
    assert primers_fleet.main(["leave"]) == 0
    assert ["ufw", "delete", "allow", *rule] in calls
    assert fleet.controllers(lab) == {}


def test_collected_logs_belong_to_whoever_ran_sudo(paired, tmp_path, monkeypatch):
    import primers_fleet
    ctrl, lab, pc, agent, run = paired
    monkeypatch.setattr(fleet, "FleetPaths", lambda: ctrl)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    owners = {}
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: owners.__setitem__(path, (uid, gid)))
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setenv("SUDO_GID", "1000")
    dest = tmp_path / "logs"
    assert primers_fleet.main(["collect", str(dest)]) == 0
    assert owners[str(dest / pc.name / "exam.jsonl")] == (1000, 1000)
    assert owners[str(dest / "SHA256SUMS")] == (1000, 1000)
