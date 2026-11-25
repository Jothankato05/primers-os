"""Check the exam kiosk's --selftest report after escape attempts (CI).

usage: check_escape.py REPORT_FILE HOME_DIR
"""
import json
import os
import sys

report_file, home = sys.argv[1], sys.argv[2]
lines = [line for line in open(report_file, encoding="utf-8") if line.startswith("{")]
assert lines, "the kiosk printed no self-test report"
report = json.loads(lines[-1])
failures = []

for name, ok in report["hardening"].items():
    if name == "toplevel_windows":
        if ok != 1:
            failures.append(f"{ok} windows open: a dialog or second window appeared")
    elif ok is not True:
        failures.append(f"hardening check failed: {name}")

if not (report["uri"] or "").endswith("/escape.html"):
    failures.append(f"the kiosk left the exam page: {report['uri']}")
if report["blocked"] < 3:
    failures.append(f"only {report['blocked']} blocked navigations (file:, view-source:, another host...)")

results = json.loads((report["title"] or "").split(" ", 1)[1]) if " " in (report["title"] or "") else {}
for key in ("display_capture", "clipboard_read"):
    if results.get(key) == "ALLOWED":
        failures.append(f"{key} was allowed")
if results.get("window_open") not in ("null", None):
    failures.append(f"window.open returned {results.get('window_open')}")

downloads = [os.path.join(d, f) for d, _, files in os.walk(home) for f in files if f.startswith("blob")]
if downloads:
    failures.append(f"a file was downloaded: {downloads}")

print(json.dumps(report, indent=2))
if failures:
    print("FAILED:\n  " + "\n  ".join(failures))
    sys.exit(1)
print("kiosk escape routes: all closed")
