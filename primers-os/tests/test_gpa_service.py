import pytest

from services.gpa_service.service import GPAService


def test_gpa_calculation(tmp_path):
    g = GPAService(str(tmp_path / "gpa.json"))
    assert g.add_course("Calculus", 3, "A", "2025-Fall")["ok"]
    assert g.add_course("Physics", 4, "b+", "2025-Fall")["ok"]
    assert g.add_course("Chemistry", 3, "C", "2026-Spring")["ok"]
    assert g.calculate_gpa("2025-Fall") == pytest.approx((4.0 * 3 + 3.3 * 4) / 7)
    report = g.get_report()
    assert report["course_count"] == 3
    assert report["highest_gpa_semester"] == "2025-Fall"
    assert report["lowest_gpa_semester"] == "2026-Spring"
    assert GPAService(str(tmp_path / "gpa.json")).get_report()["course_count"] == 3


@pytest.mark.parametrize("credits, grade", [(3, "Z"), (0, "A"), (-1, "A"), ("x", "A"), (99, "A")])
def test_rejects_bad_input(tmp_path, credits, grade):
    assert not GPAService(str(tmp_path / "g.json")).add_course("X", credits, grade, "S1")["ok"]


def test_remove_and_clear(tmp_path):
    g = GPAService(str(tmp_path / "g.json"))
    g.add_course("Art", 2, "A", "S1")
    assert g.remove_course("art", "S1")["ok"]
    assert not g.remove_course("art", "S1")["ok"]
    g.add_course("Art", 2, "A", "S1")
    g.clear()
    assert g.get_report()["cgpa"] == 0.0
