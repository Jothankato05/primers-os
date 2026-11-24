import pytest

from ai.command_interpreter.interpreter import COMMAND_MAP, CommandInterpreter


@pytest.fixture
def ci():
    return CommandInterpreter()


def test_direct_command_with_flags(ci):
    p = ci.parse("ps --sort=memory --limit=5")
    assert p.action == "list_processes"
    assert p.flags == {"sort": "memory", "limit": "5"}
    assert p.args == []
    assert p.confidence == 1.0


def test_short_flags_and_rest(ci):
    p = ci.parse('kill 1234 -y -f')
    assert p.action == "kill_process"
    assert p.args == ["1234"]
    assert p.flags == {"yes": "true", "force": "true"}
    assert ci.parse('launch firefox "https://x.y/a b"').rest == 'firefox "https://x.y/a b"'


@pytest.mark.parametrize("text, action, args", [
    ("show me processes", "list_processes", []),
    ("what's running?", "list_processes", []),
    ("kill process 4321", "kill_process", ["4321"]),
    ("open firefox", "launch", ["firefox"]),
    ("system status", "system_status", []),
    ("how is my system?", "system_status", []),
    ("any threats detected", "list_threats", []),
    ("am I safe?", "list_threats", []),
    ("what is 2 + 2", "math", ["2 + 2"]),
    ("calculate sqrt(16)", "math", ["sqrt(16)"]),
    ("find chrome", "find_process", ["chrome"]),
    ("any advice?", "advise", []),
])
def test_natural_language(ci, text, action, args):
    p = ci.parse(text)
    assert p.action == action
    assert p.args == args
    assert p.confidence < 1.0


@pytest.mark.parametrize("text", [
    "how do I run tests",       # must NOT launch a program called "tests"
    "I want to open my heart",  # not a launch either
    "tell me about threats in the news today",
])
def test_ordinary_sentences_do_not_trigger_actions(ci, text):
    assert ci.parse(text).action == "unknown"


def test_unknown_suggests_close_commands(ci):
    p = ci.parse("staus")
    assert p.action == "unknown"
    assert "status" in p.suggestions


def test_empty_input(ci):
    assert ci.parse("") is None
    assert ci.parse("   ") is None


def test_register_command_is_per_instance(ci):
    ci.register_command("hello", "plugin_hello", "Say hi")
    assert ci.parse("hello").action == "plugin_hello"
    assert "hello" not in COMMAND_MAP
    assert "hello" not in CommandInterpreter().COMMAND_MAP
    assert "hello" in ci.get_help_text()
    with pytest.raises(ValueError):
        ci.register_command("two words", "x")


def test_canonical_form(ci):
    assert ci.canonical(ci.parse("status")) == "status"
    assert ci.canonical(ci.parse("show me processes")) == "ps"
    assert ci.canonical(ci.parse("what is 3*3")) == "math 3*3"


def test_unbalanced_quotes_do_not_crash(ci):
    assert ci.parse('math "1 + 1').action == "math"
