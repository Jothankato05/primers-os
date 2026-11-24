import os
import stat

import pytest

import main
from utils import paths


def test_version(capsys):
    assert main.boot(["--version"]) == 0
    assert "1.0.0-genesis" in capsys.readouterr().out


def test_one_shot_commands(capsys):
    assert main.boot(["-c", "math 1+1", "-c", "version"]) == 0
    out = capsys.readouterr().out
    assert "= 2" in out and "PRIMERS OS" in out


def test_positional_command_and_failure_exit_code(capsys):
    assert main.boot(["math", "3*3"]) == 0
    assert "= 9" in capsys.readouterr().out
    assert main.boot(["not-a-command"]) == 1


def test_data_dir_is_private(isolated_data_dir):
    d = paths.data_dir()
    assert d == str(isolated_data_dir)
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700


def test_user_plugin_loaded(shell, capsys):
    plugin_dir = paths.user_plugin_dir()
    os.makedirs(plugin_dir, mode=0o700, exist_ok=True)
    with open(os.path.join(plugin_dir, "greet.py"), "w") as f:
        f.write("NAME='Greeter'\n"
                "def register(shell):\n"
                "    shell.register_command('greet', lambda: 'hi from user plugin', 'greet')\n")
    from services.plugin_loader.loader import PluginLoader
    loader = PluginLoader(shell)
    loader.load_all()
    assert any(p["name"] == "Greeter" for p in loader.plugins)
    shell.execute("greet")
    assert "hi from user plugin" in capsys.readouterr().out


def test_untrusted_user_plugin_skipped(shell):
    plugin_dir = paths.user_plugin_dir()
    os.makedirs(plugin_dir, mode=0o700, exist_ok=True)
    path = os.path.join(plugin_dir, "evil.py")
    with open(path, "w") as f:
        f.write("NAME='Evil'\ndef register(shell):\n    raise SystemExit('should not run')\n")
    os.chmod(path, 0o666)
    from services.plugin_loader.loader import PluginLoader
    loader = PluginLoader(shell)
    loader.load_all()
    assert not any(p["name"] == "Evil" for p in loader.plugins)


def test_broken_plugin_does_not_stop_boot(shell):
    plugin_dir = paths.user_plugin_dir()
    os.makedirs(plugin_dir, mode=0o700, exist_ok=True)
    with open(os.path.join(plugin_dir, "broken.py"), "w") as f:
        f.write("this is not python\n")
    from services.plugin_loader.loader import PluginLoader
    assert all(p["name"] != "broken" for p in PluginLoader(shell).load_all())
