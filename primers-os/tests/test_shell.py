import os

import pytest


def run(shell, capsys, line):
    ok = shell.execute(line)
    return ok, capsys.readouterr().out


def test_status_ps_and_math(shell, capsys):
    ok, out = run(shell, capsys, "status")
    assert ok and "SYSTEM STATUS" in out and "CPU" in out
    ok, out = run(shell, capsys, "ps --limit=3 --sort=mem")
    assert ok and "sorted by memory, top 3" in out
    ok, out = run(shell, capsys, "math 2^10")
    assert ok and "= 1,024" in out
    ok, out = run(shell, capsys, "what is 6*7")
    assert ok and "= 42" in out


def test_bad_flags_are_reported(shell, capsys):
    _, out = run(shell, capsys, "ps --sort=bogus")
    assert "--sort must be one of" in out
    _, out = run(shell, capsys, "ps --limit=abc")
    assert "top 20" in out


def test_kill_requires_confirmation_when_not_interactive(shell, capsys):
    pid = shell.pm.launch("sleep 30")
    try:
        _, out = run(shell, capsys, f"kill {pid}")
        assert "--yes" in out and shell.pm.get_process(pid) is not None
        _, out = run(shell, capsys, f"kill {pid} --yes")
        assert "terminated" in out
    finally:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def test_kill_protected(shell, capsys):
    _, out = run(shell, capsys, "kill 1 --yes")
    assert "protected" in out
    _, out = run(shell, capsys, f"suspend {os.getpid()}")
    assert "protected" in out


def test_learn_commands_no_longer_crash(shell, capsys):
    run(shell, capsys, "status")
    run(shell, capsys, "show me processes")
    ok, out = run(shell, capsys, "learn stats")
    assert ok and "Total commands" in out and "ps" in out
    ok, out = run(shell, capsys, "learn suggest")
    assert ok and "AI SUGGESTIONS" in out
    _, out = run(shell, capsys, "learn clear")
    assert "--yes" in out
    _, out = run(shell, capsys, "learn clear --yes")
    assert "cleared" in out


def test_task_lifecycle(shell, capsys):
    _, out = run(shell, capsys, 'task add hello interval 60 echo "hi there" | tr a-z A-Z')
    assert "scheduled" in out
    task = shell.ae.list_tasks()[0]
    assert task["command"] == 'echo "hi there" | tr a-z A-Z'
    _, out = run(shell, capsys, f"task run {task['id']}")
    assert "HI THERE" in out
    _, out = run(shell, capsys, "task add bad interval abc echo")
    assert "whole number" in out
    _, out = run(shell, capsys, "task history")
    assert task["id"] in out
    _, out = run(shell, capsys, f"task remove {task['id']}")
    assert "removed" in out


def test_gpa_flow(shell, capsys):
    _, out = run(shell, capsys, 'gpa add "Linear Algebra" 3 A- 2025-Fall')
    assert "Added course" in out
    _, out = run(shell, capsys, "gpa report")
    assert "CGPA: 3.70" in out and "Linear Algebra" in out
    _, out = run(shell, capsys, "gpa add X 3 Q S1")
    assert "Invalid grade" in out


def test_unknown_command_suggests(shell, capsys):
    ok, out = run(shell, capsys, "staus")
    assert not ok and "Did you mean" in out and "status" in out


def test_voice_is_read_only(shell, capsys):
    pid = shell.pm.launch("sleep 30")
    try:
        shell.execute_voice(f"kill {pid} --yes")
        out = capsys.readouterr().out
        assert "read-only" in out and shell.pm.get_process(pid) is not None
        shell.execute_voice("system status")
        assert "SYSTEM STATUS" in capsys.readouterr().out
    finally:
        os.kill(pid, 9)


def test_plugin_command(shell, capsys):
    ok, out = run(shell, capsys, "hello PRIMERS")
    assert ok and "Hello, PRIMERS!" in out
    _, out = run(shell, capsys, "plugins")
    assert "Sample Hello Plugin" in out


def test_command_errors_are_contained(shell, capsys, monkeypatch):
    def boom(cmd):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(shell, "_cmd_system_status", boom)
    ok, out = run(shell, capsys, "status")
    assert not ok and "kaboom" in out
    ok, _ = run(shell, capsys, "math 1+1")
    assert ok


def test_misc_commands(shell, capsys):
    for line, needle in [("help", "Available Commands"), ("version", "1.0.0-genesis"),
                         ("kernel", "KERNEL INTERFACE"), ("kernel load", "Load 1m"),
                         ("security", "SECURITY ENGINE"), ("threats", "THREAT EVENTS"),
                         ("alerts", "SYSTEM ALERTS"), ("advise", "PRIMERS ADVICE"),
                         ("graph stats", "Nodes:"), ("cyber score", "Risk Score"),
                         ("voice", "Voice Engine Status"), ("gui", "GUI Dashboard Status"),
                         ("find python", "SEARCH:"), ("modules", "")]:
        ok, out = run(shell, capsys, line)
        assert needle in out, line


def test_exit_stops_loop(shell, capsys):
    run(shell, capsys, "exit")
    assert shell._running is False
