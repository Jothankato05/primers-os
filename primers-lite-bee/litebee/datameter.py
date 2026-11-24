"""
Data meter: how much the browser downloaded this session, today and this month.

Counts the transfer size reported by each HTTP response (Content-Length,
which is the compressed size on the wire). Responses served from the disk
cache are counted too, so the meter errs on the high side.
"""

import json
import os
import time
from datetime import date
from typing import Dict, Optional

from litebee import storage


def fmt_bytes(n: float) -> str:
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if n < 100 else f"{n:.0f} {unit}"
    return f"{n:.1f} GB"


def fmt_naira(amount: float) -> str:
    if amount < 10:
        return f"₦{amount:.2f}"
    return f"₦{amount:,.0f}"


class DataMeter:
    def __init__(self, path: Optional[str] = None, naira_per_gb: float = 0.0):
        self.path = path or storage.data_file("data-usage.json")
        self.naira_per_gb = naira_per_gb
        self.session = 0
        self.saved_estimate = 0           # bytes blocked we estimate were saved
        self.days: Dict[str, int] = {}
        self._dirty = False
        self._last_save = 0.0
        self.load()

    # ------------------------------------------------------------------ #

    def add(self, nbytes: int, when: Optional[date] = None) -> None:
        if nbytes <= 0:
            return
        key = (when or date.today()).isoformat()
        self.session += nbytes
        self.days[key] = self.days.get(key, 0) + nbytes
        self._dirty = True

    def today(self) -> int:
        return self.days.get(date.today().isoformat(), 0)

    def month(self, when: Optional[date] = None) -> int:
        prefix = (when or date.today()).strftime("%Y-%m")
        return sum(v for k, v in self.days.items() if k.startswith(prefix))

    def cost(self, nbytes: int) -> Optional[float]:
        if self.naira_per_gb <= 0:
            return None
        return nbytes / (1024 ** 3) * self.naira_per_gb

    def label(self) -> str:
        text = f"{fmt_bytes(self.today())} today"
        c = self.cost(self.today())
        if c is not None:
            text += f" · {fmt_naira(c)}"
        return text

    def tooltip(self) -> str:
        lines = [f"This session: {fmt_bytes(self.session)}",
                 f"Today: {fmt_bytes(self.today())}",
                 f"This month: {fmt_bytes(self.month())}"]
        if self.naira_per_gb > 0:
            lines.append(f"Cost this month: {fmt_naira(self.cost(self.month()))} "
                         f"at ₦{self.naira_per_gb:,.0f}/GB")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.days = {k: int(v) for k, v in data.get("days", {}).items()}
        except (OSError, ValueError, AttributeError):
            self.days = {}

    def save(self, force: bool = False) -> None:
        if not self._dirty and not force:
            return
        # Keep roughly a year of daily totals
        if len(self.days) > 400:
            for k in sorted(self.days)[:-400]:
                del self.days[k]
        storage.write_private(self.path, json.dumps({"days": self.days}))
        self._dirty = False
        self._last_save = time.time()
