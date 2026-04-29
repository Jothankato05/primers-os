import json
import os
from typing import List, Dict, Optional
from utils.logger import PrimersLogger

class GPAService:
    """
    GPA Calculator and academic tracker.
    Stores data in logs/gpa_data.json
    """
    
    GRADE_SCALE = {
        "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
        "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3, "D": 1.0, "F": 0.0
    }

    def __init__(self):
        self.logger = PrimersLogger.get_logger("gpa_service")
        # Ensure the path is correct relative to the primers-os directory
        self.data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs", "gpa_data.json")
        self.courses = []
        self.load()

    def add_course(self, name: str, credit_hours: float, grade: str, semester: str) -> dict:
        grade = grade.upper()
        if grade not in self.GRADE_SCALE:
            self.logger.error(f"Invalid grade: {grade}")
            return {"ok": False, "error": f"Invalid grade: {grade}"}
        
        course = {
            "name": name,
            "credit_hours": float(credit_hours),
            "grade": grade,
            "semester": semester
        }
        self.courses.append(course)
        self.save()
        return {"ok": True}

    def remove_course(self, name: str, semester: str) -> dict:
        initial_count = len(self.courses)
        self.courses = [c for c in self.courses if not (c["name"].lower() == name.lower() and c["semester"] == semester)]
        if len(self.courses) < initial_count:
            self.save()
            return {"ok": True}
        return {"ok": False, "error": "not found"}

    def calculate_gpa(self, semester: Optional[str] = None) -> float:
        relevant_courses = self.courses
        if semester:
            relevant_courses = [c for c in self.courses if c["semester"] == semester]
        
        if not relevant_courses:
            return 0.0
        
        total_points = sum(self.GRADE_SCALE[c["grade"]] * c["credit_hours"] for c in relevant_courses)
        total_credits = sum(c["credit_hours"] for c in relevant_courses)
        
        return total_points / total_credits if total_credits > 0 else 0.0

    def get_report(self) -> dict:
        if not self.courses:
            return {
                "cgpa": 0.0,
                "total_credits": 0.0,
                "course_count": 0,
                "semesters": {},
                "highest_gpa_semester": "N/A",
                "lowest_gpa_semester": "N/A"
            }
        
        semesters_data = {}
        all_semesters = set(c["semester"] for c in self.courses)
        
        for sem in all_semesters:
            sem_courses = [c for c in self.courses if c["semester"] == sem]
            sem_gpa = self.calculate_gpa(sem)
            sem_credits = sum(c["credit_hours"] for c in sem_courses)
            semesters_data[sem] = {
                "gpa": sem_gpa,
                "credits": sem_credits,
                "courses": sem_courses
            }
        
        cgpa = self.calculate_gpa()
        total_credits = sum(c["credit_hours"] for c in self.courses)
        
        highest_sem = max(semesters_data, key=lambda k: semesters_data[k]["gpa"]) if semesters_data else "N/A"
        lowest_sem = min(semesters_data, key=lambda k: semesters_data[k]["gpa"]) if semesters_data else "N/A"
        
        return {
            "cgpa": cgpa,
            "total_credits": total_credits,
            "course_count": len(self.courses),
            "semesters": semesters_data,
            "highest_gpa_semester": highest_sem,
            "lowest_gpa_semester": lowest_sem
        }

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
            with open(self.data_path, 'w') as f:
                json.dump({"courses": self.courses}, f, indent=4)
        except Exception as e:
            self.logger.error(f"Failed to save GPA data: {e}")

    def load(self) -> None:
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, 'r') as f:
                    data = json.load(f)
                    self.courses = data.get("courses", [])
            except Exception as e:
                self.logger.error(f"Failed to load GPA data: {e}")
                self.courses = []

    def clear(self) -> None:
        self.courses = []
        self.save()
