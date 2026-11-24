"""
Session and settings persistence.

Open tabs are written atomically after every navigation, so a sudden power
cut never loses them: the next start reopens exactly what was open.
"""

from dataclasses import asdict, dataclass, field
from typing import List

from litebee import storage

MAX_TABS_RESTORED = 30


@dataclass
class Settings:
    mode: str = "auto"                 # auto | full | lite | ultra
    search_engine: str = "duckduckgo-lite"
    naira_per_gb: float = 0.0          # 0 = don't show cost
    homepage: str = "bee:home"
    restore_session: bool = True
    zoom: float = 1.0

    @classmethod
    def load(cls) -> "Settings":
        raw = storage.read_json(storage.data_file("settings.json"), {})
        s = cls()
        if isinstance(raw, dict):
            for key, value in raw.items():
                if hasattr(s, key) and isinstance(value, type(getattr(s, key))):
                    setattr(s, key, value)
                elif key in ("naira_per_gb", "zoom") and isinstance(value, (int, float)):
                    setattr(s, key, float(value))
        if s.mode not in ("auto", "full", "lite", "ultra"):
            s.mode = "auto"
        return s

    def save(self) -> None:
        import json
        storage.write_private(storage.data_file("settings.json"), json.dumps(asdict(self), indent=2))


@dataclass
class Session:
    tabs: List[str] = field(default_factory=list)
    active: int = 0

    @classmethod
    def load(cls) -> "Session":
        raw = storage.read_json(storage.data_file("session.json"), {})
        if not isinstance(raw, dict):
            return cls()
        tabs = [t for t in raw.get("tabs", []) if isinstance(t, str) and t][:MAX_TABS_RESTORED]
        active = raw.get("active", 0)
        if not isinstance(active, int) or not 0 <= active < max(1, len(tabs)):
            active = 0
        return cls(tabs, active)

    def save(self) -> None:
        import json
        storage.write_private(storage.data_file("session.json"),
                              json.dumps({"tabs": self.tabs[:MAX_TABS_RESTORED], "active": self.active}))
