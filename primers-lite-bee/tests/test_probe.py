"""The probe's recorder: what an exam site loaded, host by host."""

from litebee.probe import Recorder


def test_hosts_ports_and_schemes_are_recorded():
    r = Recorder("https://cbt.uni.edu.ng/login/index.php")
    r.record("https://cbt.uni.edu.ng/login/index.php", "page")
    r.record("https://cbt.uni.edu.ng/theme/styles.php", "resource")
    r.record("https://CDN.jsdelivr.net./npm/mathjax@3/es5/tex-mml-chtml.js")
    r.record("http://media.uni.edu.ng:8080/v.mp4")
    r.record("wss://live.uni.edu.ng/socket")
    r.record("http://[2001:db8::7]:8443/x")
    rep = r.report()
    assert rep["main_host"] == "cbt.uni.edu.ng"
    assert rep["hosts"]["cbt.uni.edu.ng"] == {"schemes": ["https"], "ports": [443], "requests": 2,
                                              "first": "https://cbt.uni.edu.ng/login/index.php",
                                              "kinds": ["page", "resource"]}
    assert rep["hosts"]["cdn.jsdelivr.net"]["ports"] == [443]
    assert rep["hosts"]["media.uni.edu.ng"]["ports"] == [8080]
    assert rep["hosts"]["live.uni.edu.ng"]["schemes"] == ["wss"]
    assert rep["hosts"]["2001:db8::7"]["ports"] == [8443]


def test_no_network_schemes_are_noted_not_counted():
    r = Recorder("https://cbt.uni.edu.ng/")
    for uri in ("data:image/png;base64,AAAA", "blob:https://cbt.uni.edu.ng/123", "about:blank", "", "not a url"):
        r.record(uri)
    assert r.report()["hosts"] == {}
    assert r.report()["other_schemes"] == ["about", "blob", "data"]


def test_failures_are_kept_but_bounded(tmp_path):
    r = Recorder("https://cbt.uni.edu.ng/")
    for i in range(250):
        r.fail(f"https://gone.example/{i}", "Could not resolve host")
    assert len(r.report()["failed"]) == 200
    path = tmp_path / "report.json"
    r.save(str(path))
    assert path.read_text().startswith("{")
