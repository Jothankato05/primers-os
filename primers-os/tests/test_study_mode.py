import os

import pytest

from core import study_mode as sm


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return str(tmp_path / "state" / "primers" / "study")


def test_start_writes_a_session_the_panel_and_browser_can_read(state):
    session = sm.start(25, now=1000)
    assert session == sm.Session(1000, 1000 + 25 * 60, 25)
    text = open(state).read()
    assert "until=2500\n" in text and "started=1000\n" in text and "minutes=25\n" in text
    assert sm.read() == session
    assert sm.current(now=1001) == session
    assert sm.current(now=2500) is None          # finished sessions are not current


@pytest.mark.parametrize("minutes", [0, -5, 241])
def test_start_rejects_silly_lengths(state, minutes):
    with pytest.raises(ValueError):
        sm.start(minutes)
    assert not os.path.exists(state)


def test_stop(state):
    assert sm.stop() is None
    sm.start(10)
    assert sm.stop().minutes == 10
    assert sm.current() is None and not os.path.exists(state)


def test_damaged_state_is_ignored(state):
    os.makedirs(os.path.dirname(state))
    with open(state, "w") as f:
        f.write("until=soon\n")
    assert sm.read() is None and sm.current() is None


@pytest.mark.parametrize("seconds, text", [(5, "5 s"), (60, "1 min"), (61, "2 min"),
                                           (1500, "25 min"), (3600, "1 h 00 min"), (5400, "1 h 30 min")])
def test_format_left(seconds, text):
    assert sm.format_left(seconds) == text


def test_wait_for_end_notifies_when_the_timer_runs_out(state):
    clock = [1000.0]
    sm.start(1, now=clock[0])
    done = []

    def sleep(s):
        clock[0] += s
    assert sm.wait_for_end(on_done=done.append, sleep=sleep, clock=lambda: clock[0]).minutes == 1
    assert [s.minutes for s in done] == [1]
    assert not os.path.exists(state)


def test_wait_for_end_is_quiet_when_stopped_or_replaced(state):
    clock = [1000.0]
    sm.start(5, now=clock[0])
    done = []

    def stop_then_sleep(s):
        sm.stop()
        clock[0] += s
    assert sm.wait_for_end(on_done=done.append, sleep=stop_then_sleep, clock=lambda: clock[0]) is None

    sm.start(5, now=clock[0])

    def replace_then_sleep(s):
        sm.start(30, now=clock[0] + 1)
        clock[0] += s
    assert sm.wait_for_end(on_done=done.append, sleep=replace_then_sleep, clock=lambda: clock[0]) is None
    assert done == [] and sm.read().minutes == 30   # the new session is left alone


def test_brain_study_commands(shell, capsys, state, monkeypatch):
    import primers_study
    spawned = []
    monkeypatch.setattr(primers_study, "spawn_end_notice", lambda: spawned.append(True))

    shell.execute("study")
    assert "off" in capsys.readouterr().out

    shell.execute("focus for 30 minutes")
    out = capsys.readouterr().out
    assert "Study Mode on for 30 min" in out and spawned == [True]
    assert sm.current().minutes == 30

    shell.execute("study")
    assert "30 min left" in capsys.readouterr().out

    shell.execute("stop studying")
    assert "Study Mode ended" in capsys.readouterr().out and sm.current() is None

    shell.execute("start a study session")
    assert sm.current().minutes == sm.DEFAULT_MINUTES
    shell.execute("study stop")
    shell.execute("study 999")
    assert "1-240 minutes" in capsys.readouterr().out and sm.current() is None


def test_cli(state, capsys, monkeypatch):
    import primers_study
    monkeypatch.setattr(primers_study, "spawn_end_notice", lambda: None)
    assert primers_study.main(["status"]) == 0
    assert "off" in capsys.readouterr().out
    assert primers_study.main(["start", "15"]) == 0
    assert primers_study.main(["status"]) == 0
    assert "15 min left of 15 min" in capsys.readouterr().out
    assert primers_study.main(["stop"]) == 0
    assert primers_study.main(["start", "0"]) == 2


@pytest.mark.parametrize("text, action, args", [
    ("study 25", "study", ["25"]), ("study for 45 minutes", "study", ["45"]),
    ("start studying for 50 mins", "study", ["50"]), ("focus 20", "study", ["20"]),
    ("start a study session", "study_start", []), ("stop studying", "study", ["stop"]),
    ("end study mode", "study", ["end"]), ("study stop", "study", ["stop"]), ("study", "study", []),
])
def test_interpreter_study_phrases(text, action, args):
    from ai.command_interpreter.interpreter import CommandInterpreter
    parsed = CommandInterpreter().parse(text)
    assert (parsed.action, parsed.args) == (action, args)
