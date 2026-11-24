import math

import pytest

from services.math_engine.engine import MathEngine

E = MathEngine.evaluate


@pytest.mark.parametrize("expr, expected", [
    ("1 + 2 * 3", 7),
    ("(1 + 2) * 3", 9),
    ("2^10", 1024),
    ("2 ** 10", 1024),
    ("7 // 2", 3),
    ("7 % 4", 3),
    ("-5 + 3", -2),
    ("sqrt(144) + 1", 13),
    ("factorial(5)", 120),
    ("max(3, 9, 4)", 9),
    ("gcd(12, 18)", 6),
    ("6 × 7", 42),
    ("10 ÷ 4", 2.5),
])
def test_arithmetic(expr, expected):
    assert E(expr) == expected


def test_constants_and_trig():
    assert E("pi") == pytest.approx(math.pi)
    assert E("sin(pi / 2)") == 1
    assert E("log10(1000)") == 3


@pytest.mark.parametrize("expr", [
    "().__class__",
    "__import__('os').system('true')",
    "open('/etc/passwd')",
    "[1, 2][0]",
    "lambda: 1",
    "x",
    "'a' * 3",
    "sqrt(x=4)",
])
def test_rejects_non_math(expr):
    assert str(E(expr)).startswith("Error:")


@pytest.mark.parametrize("expr", ["9^9^9", "10 ** 100000", "factorial(100000)", "2.0 ** 99999"])
def test_resource_limits(expr):
    assert E(expr) == "Error: Result too large." or str(E(expr)).startswith("Error:")


def test_errors():
    assert E("1/0") == "Error: Division by zero."
    assert E("") == "Error: Empty expression."
    assert E("1 +") == "Error: Invalid expression."
    assert E("1+" * 400 + "1") == "Error: Expression too long."
    assert str(E("sqrt(-1)")).startswith("Error:")


def test_format_result():
    assert MathEngine.format_result(1024) == "= 1,024"
    assert MathEngine.format_result(0.5) == "= 0.5"
    assert MathEngine.format_result("Error: x") == "Error: x"
