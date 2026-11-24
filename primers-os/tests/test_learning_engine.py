import json
import os
import stat

from ai.learning_engine.engine import LearningEngine


def test_empty_engine():
    le = LearningEngine()
    stats = le.get_stats()
    assert stats["total_commands"] == 0
    assert stats["top_commands"] == []
    assert le.suggest() == ["status", "ps", "help"]
    assert le.suggest([]) == ["status", "ps", "help"]


def test_stats_and_suggestions(tmp_path):
    le = LearningEngine(str(tmp_path / "u.jsonl"))
    for cmd in ["status", "ps", "status", "ps", "status", "threats"]:
        le.log_command(cmd, "x", [])
    stats = le.get_stats()
    assert stats["total_commands"] == 6
    assert stats["most_used"][0] == {"command": "status", "count": 3}
    assert stats["top_commands"][0] == ("status", 3)
    assert {"sequence": "status→ps", "count": 2} in stats["command_sequences"]
    # after "status" the user usually runs "ps"
    assert le.suggest(["status"])[0] == "ps"
    assert len(le.suggest()) == 3


def test_history_persists_privately(tmp_path):
    path = tmp_path / "u.jsonl"
    le = LearningEngine(str(path))
    le.log_command("status", "system_status", [])
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert LearningEngine(str(path)).get_stats()["total_commands"] == 1


def test_corrupt_lines_are_skipped(tmp_path):
    path = tmp_path / "u.jsonl"
    path.write_text(json.dumps({"command": "ps", "timestamp": 1, "hour": 3}) + "\nnot json\n{}\n")
    assert LearningEngine(str(path)).get_stats()["total_commands"] == 1


def test_clear(tmp_path):
    path = tmp_path / "u.jsonl"
    le = LearningEngine(str(path))
    le.log_command("ps", "list_processes", [])
    le.clear()
    assert le.get_stats()["total_commands"] == 0
    assert not path.exists()


def test_ignores_blank_commands(tmp_path):
    le = LearningEngine(str(tmp_path / "u.jsonl"))
    le.log_command("   ", "x", [])
    assert le.get_stats()["total_commands"] == 0
