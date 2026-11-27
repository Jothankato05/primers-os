"""
PRIMERS OS - Knowledge layer ("Ask Primers", offline).

Loads the Primers knowledge base (Markdown with YAML front matter), chunks it
by heading, and answers questions by retrieval - never by invention:

1. Emergencies first: anything that sounds like danger gets Nigeria's 112
   and SecureLink before anything else.
2. Ready answers (the FAQ section) when a question matches one closely.
3. Otherwise the best-matching section(s), quoted from the file.
4. No match: say so and give the contact route.

Items marked ``[VERIFY ...]`` are shown as "(unconfirmed)".
"""

import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILE_NAME = "PRIMERS_KNOWLEDGE.md"
SEARCH_PATHS = [
    os.path.join(BASE_DIR, "knowledge", FILE_NAME),
    os.path.join("/usr/share/primers/knowledge", FILE_NAME),
]

EMERGENCY_NUMBER = "112"
CONTACT_ROUTE = "the Primers Group website, primersgroup.ng"

_DANGER = re.compile(
    r"\b(i'?m in danger|in danger|help me|emergency|attack(ed|ing)?|kidnap\w*|rob(bed|bery|bers)?|"
    r"fire|burning|accident|bleeding|unconscious|assault\w*|threaten\w*|gun|knife|stab\w*|"
    r"rape\w*|being followed|someone is following)\b",
    re.IGNORECASE,
)

_STOPWORDS = set("""
a an the is are was were be been being am do does did of to in on at for by with from and or not
no it its this that these those what which who whom whose how why where when can could should would
will shall may might must i me my you your we our us they them their he she his her about into than
then there here so if as any all some tell please give show me primers's s
""".split())

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


def mark_unverified(text: str) -> str:
    """Replace [VERIFY ...] markers with a plain '(unconfirmed)' note."""
    return re.sub(r"\s*\[VERIFY[^\]]*\]", " (unconfirmed)", text)


@dataclass
class Chunk:
    title: str
    text: str
    tokens: List[str] = field(default_factory=list)
    title_tokens: List[str] = field(default_factory=list)


@dataclass
class FAQ:
    question: str
    answer: str
    tokens: List[str] = field(default_factory=list)


@dataclass
class Answer:
    kind: str                     # emergency | faq | section | none
    text: str
    sources: List[str] = field(default_factory=list)
    emergency: bool = False


class KnowledgeBase:
    def __init__(self, path: Optional[str] = None):
        self.path = path or self._locate()
        self.metadata: Dict[str, str] = {}
        self.chunks: List[Chunk] = []
        self.faqs: List[FAQ] = []
        self.glossary: Dict[str, str] = {}
        self._df: Counter = Counter()
        self._avg_len = 1.0
        if self.path and os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.load_text(f.read())

    @staticmethod
    def _locate() -> Optional[str]:
        env = os.environ.get("PRIMERS_KNOWLEDGE")
        for candidate in ([env] if env else []) + SEARCH_PATHS:
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    @property
    def available(self) -> bool:
        return bool(self.chunks)

    # ------------------------------------------------------------------ #
    #  Parsing
    # ------------------------------------------------------------------ #

    def load_text(self, text: str) -> None:
        body = text
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                for line in text[3:end].strip().splitlines():
                    key, sep, value = line.partition(":")
                    if sep:
                        self.metadata[key.strip()] = value.strip()
                body = text[end + 4:]

        self.chunks, self.faqs = [], []
        section, subsection, buf = "", "", []

        def flush():
            content = "\n".join(buf).strip().strip("-").strip()
            if content and (section or subsection):
                title = f"{section} › {subsection}" if subsection else section
                self.chunks.append(Chunk(title, content))

        for line in body.splitlines():
            if line.startswith("## "):
                flush()
                section, subsection, buf = line[3:].strip(), "", []
            elif line.startswith("### "):
                flush()
                subsection, buf = line[4:].strip(), []
            elif line.startswith("# "):
                continue
            else:
                buf.append(line)
        flush()

        # Ready answers: "**Question?**" followed by an answer paragraph
        for chunk in self.chunks:
            if "ready answers" in chunk.title.lower() or "faq" in chunk.title.lower():
                for m in re.finditer(r"\*\*(.+?)\*\*\s*\n(.+?)(?=\n\s*\n|\Z)", chunk.text, re.S):
                    q, a = m.group(1).strip(), " ".join(m.group(2).split())
                    self.faqs.append(FAQ(q, a, tokenize(q)))

        # Glossary table: "| Term | Meaning |"
        self.glossary = {}
        for chunk in self.chunks:
            if "glossary" in chunk.title.lower():
                for line in chunk.text.splitlines():
                    cells = [c.strip() for c in line.strip().strip("|").split("|")]
                    if len(cells) == 2 and cells[0] and not set(cells[0]) <= set("-: ") \
                            and cells[0].lower() != "term":
                        self.glossary[cells[0]] = cells[1]

        for chunk in self.chunks:
            chunk.title_tokens = tokenize(chunk.title)
            chunk.tokens = tokenize(chunk.text) + chunk.title_tokens * 3
        self._df = Counter()
        for chunk in self.chunks:
            self._df.update(set(chunk.tokens))
        self._avg_len = (sum(len(c.tokens) for c in self.chunks) / len(self.chunks)) if self.chunks else 1.0

    # ------------------------------------------------------------------ #
    #  Retrieval
    # ------------------------------------------------------------------ #

    def _bm25(self, query: List[str], chunk: Chunk, k1: float = 1.4, b: float = 0.75) -> float:
        n = len(self.chunks)
        tf = Counter(chunk.tokens)
        score = 0.0
        for term in set(query):
            if term not in tf:
                continue
            idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
            freq = tf[term]
            score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * len(chunk.tokens) / self._avg_len))
        return score

    def search(self, query: str, k: int = 3) -> List[Tuple[float, Chunk]]:
        q = tokenize(query)
        if not q:
            return []
        qset = set(q)
        # A section whose heading names the subject beats one that only mentions it
        scored = [(self._bm25(q, c) + 4.0 * len(qset & set(c.title_tokens)) / len(qset), c)
                  for c in self.chunks]
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda s: s[0], reverse=True)
        return scored[:k]

    def match_faq(self, query: str) -> Optional[FAQ]:
        """A ready answer only counts when question and FAQ mostly overlap both ways."""
        q = set(tokenize(query))
        if not q:
            return None
        best, best_score = None, 0.0
        for faq in self.faqs:
            f = set(faq.tokens)
            if not f:
                continue
            overlap = len(q & f)
            score = min(overlap / len(q), overlap / len(f))
            if score > best_score:
                best, best_score = faq, score
        return best if best_score >= 0.6 else None

    @staticmethod
    def is_emergency(text: str) -> bool:
        return bool(_DANGER.search(text or ""))

    @staticmethod
    def _prettify(line: str) -> str:
        """Turn Markdown table rows into 'Field: value' lines."""
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            cells = [c for c in cells if c]
            if len(cells) == 2:
                return f"{cells[0]}: {cells[1]}"
            return " - ".join(cells)
        return stripped

    def _excerpt(self, chunk: Chunk, query_tokens: List[str], max_lines: int) -> str:
        lines = [ln for ln in chunk.text.splitlines()
                 if ln.strip() and not set(ln.strip()) <= set("|-: ")]
        q = set(query_tokens)
        about_topic = bool(q & set(chunk.title_tokens))
        if not about_topic:
            hits = [ln for ln in lines if q & set(tokenize(ln))]
            if hits:
                lines = hits
        pretty = [self._prettify(ln) for ln in lines]
        # Drop the header row of a table ("Field: Value", "Metric: Target")
        if pretty and lines and lines[0].strip().startswith("|") and len(pretty) > 1 and about_topic:
            pretty = pretty[1:]
        out = "\n".join(pretty[:max_lines])
        if len(pretty) > max_lines:
            out += "\n…"
        return out

    def define(self, question: str) -> Optional[Tuple[str, str]]:
        q = set(tokenize(question))
        for term, meaning in self.glossary.items():
            if q and set(tokenize(term)) == q:
                return term, meaning
        return None

    def _lookup(self, question: str, max_lines: int) -> Answer:
        defined = self.define(question)
        if defined:
            return Answer("glossary", f"{defined[0]}: {defined[1]}", ["Glossary"])
        faq = self.match_faq(question)
        if faq:
            return Answer("faq", mark_unverified(faq.answer), [f"Ready answers › {faq.question}"])

        q = tokenize(question)
        results = self.search(question)
        if results:
            score, best = results[0]
            coverage = len(set(q) & set(best.tokens)) / len(set(q)) if q else 0
            if score >= 0.8 and coverage >= 0.6:
                sources = [best.title] + [c.title for s, c in results[1:] if s >= score * 0.6]
                return Answer("section", mark_unverified(self._excerpt(best, q, max_lines)), sources)
        return Answer("none", "I don't have that information. "
                              f"You can reach Primers through {CONTACT_ROUTE}.")

    def answer(self, question: str, max_lines: int = 14) -> Answer:
        question = (question or "").strip()
        if not question:
            return Answer("none", "Ask me anything about Primers - e.g. 'what is Veltis One?'")

        if not self.available:
            found = Answer("none", "The Primers knowledge base is not installed on this system.")
        else:
            found = self._lookup(question, max_lines)

        if self.is_emergency(question):
            banner = (f"If you are in danger, call {EMERGENCY_NUMBER} now (Nigeria emergency line).\n"
                      "SecureLink - Primers' emergency broadcasting - routes alerts to fire services, "
                      "police and road safety responders around you.")
            text = banner if found.kind == "none" else f"{banner}\n\n{found.text}"
            return Answer("emergency", text, ["Emergencies first"] + found.sources, emergency=True)
        return found

    def topics(self) -> List[str]:
        seen, out = set(), []
        for c in self.chunks:
            top = c.title.split(" › ")[0]
            if top not in seen:
                seen.add(top)
                out.append(top)
        return out
