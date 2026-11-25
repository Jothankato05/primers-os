"""Check the probe's report from tests/probe/probe.html (CI, real WebKit)."""
import json
import sys

rep = json.load(open(sys.argv[1]))
hosts = rep["hosts"]
want = {"127.0.0.1": 8767, "localhost": 8768, "127.0.0.2": 8767, "127.0.0.3": 8767}
problems = []
for host, port in want.items():
    if host not in hosts:
        problems.append(f"{host} not recorded")
    elif port not in hosts[host]["ports"]:
        problems.append(f"{host}: port {port} not recorded ({hosts[host]['ports']})")
if rep["main_host"] != "127.0.0.1":
    problems.append(f"main host {rep['main_host']}")
kinds = set(hosts.get("localhost", {}).get("kinds", []))
if "redirect" not in kinds and "page" not in kinds:
    problems.append(f"the redirect to localhost wasn't seen ({kinds})")
if hosts.get("127.0.0.1", {}).get("requests", 0) < 3:
    problems.append("too few requests to the exam site itself")
print(json.dumps(rep, indent=2))
if problems:
    print("FAIL: " + "; ".join(problems))
    sys.exit(1)
print("probe report OK: " + ", ".join(sorted(hosts)))
