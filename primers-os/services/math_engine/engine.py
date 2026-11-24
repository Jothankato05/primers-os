"""
PRIMERS OS — Math Engine Service
Safe mathematical expression evaluator.

Expressions are parsed with :mod:`ast` and only arithmetic nodes, numeric
literals, whitelisted constants and whitelisted functions are evaluated —
no ``eval``, no attribute access, no subscripts. Size limits stop inputs
such as ``9^9^9`` or ``factorial(10^9)`` from freezing the shell.
"""

import ast
import math
import operator
from typing import Union

Number = Union[int, float]

MAX_EXPRESSION_LENGTH = 500
MAX_EXPONENT = 10_000          # largest allowed power for big bases
MAX_RESULT_DIGITS = 4_000      # integers longer than this are rejected
MAX_FACTORIAL = 1_000

CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
}


def _factorial(n):
    if isinstance(n, float):
        if not n.is_integer():
            raise ValueError("factorial() only accepts whole numbers")
        n = int(n)
    if n > MAX_FACTORIAL:
        raise ValueError(f"factorial() is limited to n ≤ {MAX_FACTORIAL}")
    return math.factorial(n)


FUNCTIONS = {
    "abs": abs, "round": round, "min": min, "max": max,
    "int": int, "float": float,
    "sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "ceil": math.ceil, "floor": math.floor,
    "log": math.log, "ln": math.log, "log2": math.log2, "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "degrees": math.degrees, "radians": math.radians,
    "hypot": math.hypot, "gcd": math.gcd, "lcm": math.lcm,
    "factorial": _factorial,
    "pow": lambda a, b: _power(a, b),
}

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class MathError(Exception):
    pass


def _power(base, exp):
    if isinstance(base, (int, float)) and isinstance(exp, (int, float)):
        if abs(exp) > MAX_EXPONENT and abs(base) not in (0, 1):
            raise MathError("Result too large.")
        if isinstance(base, int) and isinstance(exp, int) and exp > 0 and abs(base) > 1:
            if exp * math.log10(abs(base)) > MAX_RESULT_DIGITS:
                raise MathError("Result too large.")
    return operator.pow(base, exp)


def _check_size(value):
    if isinstance(value, int) and not isinstance(value, bool):
        if value.bit_length() > MAX_RESULT_DIGITS * 3.33:
            raise MathError("Result too large.")
    return value


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise MathError(f"Unsupported value: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise MathError(f"Unknown name: '{node.id}'")
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow):
            return _check_size(_power(left, right))
        if type(node.op) in _BIN_OPS:
            return _check_size(_BIN_OPS[type(node.op)](left, right))
        raise MathError("Unsupported operator.")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            name = getattr(node.func, "id", "?")
            raise MathError(f"Unknown function: '{name}'")
        if node.keywords:
            raise MathError("Keyword arguments are not supported.")
        args = [_eval(a) for a in node.args]
        return _check_size(FUNCTIONS[node.func.id](*args))
    raise MathError("Unsupported expression.")


class MathEngine:
    """
    Safe expression evaluator.
    Supports: arithmetic (+ - * / // % ^ **), trigonometry, logarithms,
    constants (pi, e, tau) and common functions.
    """

    @staticmethod
    def evaluate(expression: str) -> Union[Number, str]:
        """Evaluate an expression string. Returns the result or an error string."""
        clean = (expression or "").strip()
        if not clean:
            return "Error: Empty expression."
        if len(clean) > MAX_EXPRESSION_LENGTH:
            return "Error: Expression too long."

        # ^ means power, as on a calculator; × and ÷ are accepted too
        clean = clean.replace("^", "**").replace("×", "*").replace("÷", "/")

        try:
            tree = ast.parse(clean, mode="eval")
            result = _eval(tree)
        except ZeroDivisionError:
            return "Error: Division by zero."
        except OverflowError:
            return "Error: Result too large."
        except MathError as e:
            return f"Error: {e}"
        except SyntaxError:
            return "Error: Invalid expression."
        except (TypeError, ValueError) as e:
            return f"Error: {e}"
        except RecursionError:
            return "Error: Expression too deeply nested."

        if isinstance(result, complex):
            return "Error: Complex result."
        if isinstance(result, float) and result.is_integer() and abs(result) < 1e16:
            return int(result)
        return result

    @staticmethod
    def format_result(result: Union[Number, str]) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, bool):
            return f"= {result}"
        if isinstance(result, int):
            try:
                return f"= {result:,}"
            except ValueError:  # beyond Python's int→str digit limit
                return "Error: Result too large to display."
        return f"= {result:.10g}"
