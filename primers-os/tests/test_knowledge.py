import pytest

from services.knowledge.engine import KnowledgeBase, mark_unverified, tokenize

SAMPLE = """---
id: test-kb
version: 9.9
---

# Title

## 1. Identity

| Field | Value |
|---|---|
| Company | Example Group |
| Headquarters | Abuja, Nigeria |
| Domain | example.ng [VERIFY ownership] |

## 4. Products

### 4.1 Widget — Live
A widget that counts bees in a hive.
- Works offline.

## 12. Ready Answers

**Who founded Example?**
Ada Lovelace, Founder.

**Does it work without internet?**
Parts of it do.

## 13. Glossary

| Term | Meaning |
|---|---|
| Lab Mode | Shared-machine mode that wipes the session |
"""


@pytest.fixture
def kb():
    k = KnowledgeBase(path="/nonexistent")
    k.load_text(SAMPLE)
    return k


def test_parsing(kb):
    assert kb.metadata["version"] == "9.9"
    titles = [c.title for c in kb.chunks]
    assert "1. Identity" in titles and "4. Products › 4.1 Widget — Live" in titles
    assert [f.question for f in kb.faqs] == ["Who founded Example?", "Does it work without internet?"]
    assert kb.glossary == {"Lab Mode": "Shared-machine mode that wipes the session"}


def test_faq_glossary_and_sections(kb):
    assert kb.answer("who founded example").text == "Ada Lovelace, Founder."
    assert kb.answer("what is lab mode").kind == "glossary"
    a = kb.answer("tell me about the widget")
    assert a.kind == "section" and "counts bees" in a.text and a.sources[0].endswith("Widget — Live")
    hq = kb.answer("where is the headquarters")
    assert hq.text == "Headquarters: Abuja, Nigeria"


def test_unverified_items_are_marked(kb):
    a = kb.answer("domain")
    assert "(unconfirmed)" in a.text and "VERIFY" not in a.text
    assert mark_unverified("x [VERIFY before quoting] y") == "x (unconfirmed) y"


def test_never_invents(kb):
    a = kb.answer("what is the price of bitcoin")
    assert a.kind == "none" and "primersgroup.ng" in a.text


@pytest.mark.parametrize("q", ["I'm in danger", "help me someone is following me",
                               "there is a fire in my hostel", "I was robbed"])
def test_emergencies_first(kb, q):
    a = kb.answer(q)
    assert a.emergency and a.text.startswith("If you are in danger, call 112")


def test_missing_file():
    k = KnowledgeBase(path="/nonexistent")
    assert not k.available
    assert "not installed" in k.answer("who founded primers").text


def test_shipped_knowledge_base_loads():
    k = KnowledgeBase()
    assert k.available and len(k.chunks) > 30 and len(k.faqs) >= 10
    assert "Jothan Jerry Kato" in k.answer("who founded Primers?").text
    assert "Veltis One" in k.answer("what is veltis one").sources[0]
    assert k.answer("is SafeCare a primers product").kind == "section"


def test_tokenize_drops_stopwords():
    assert tokenize("What is the Veltis One card?") == ["veltis", "one", "card"]


def test_shell_ask_and_question_fallback(shell, capsys):
    shell.execute("ask who founded Primers?")
    assert "Jothan Jerry Kato" in capsys.readouterr().out
    shell.execute("what is exam mode?")
    assert "lockdown" in capsys.readouterr().out.lower()
    shell.execute("help me I'm in danger")
    assert "112" in capsys.readouterr().out
    shell.execute("ask")
    assert "ASK PRIMERS" in capsys.readouterr().out


def test_questions_route_to_ask_but_commands_still_win(shell):
    ci = shell.ci
    assert ci.parse("who is the CTO?").action == "ask"
    assert ci.parse("how is my system?").action == "system_status"
    assert ci.parse("what is 2+2").action == "math"
    assert ci.parse("status").action == "system_status"
    assert ci.parse("xyzzy").action == "unknown"


def test_voice_can_ask(shell, capsys):
    shell.execute_voice("who founded primers")
    assert "Jothan" in capsys.readouterr().out
