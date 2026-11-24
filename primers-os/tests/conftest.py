import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets its own PRIMERS data directory."""
    data = tmp_path / "primers-data"
    monkeypatch.setenv("PRIMERS_DATA_DIR", str(data))
    monkeypatch.delenv("PRIMERS_LOG_DIR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    from interface.cli.shell import C
    C.configure(False)
    return data


@pytest.fixture
def shell(isolated_data_dir):
    from configs.settings import Settings
    from main import build_shell
    sh = build_shell(Settings(), interactive=False)
    yield sh
    sh.shutdown()
