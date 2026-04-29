"""
PRIMERS OS — Math Engine Service
Safe mathematical expression evaluator.
"""

import math
import operator
import re
from typing import Union


# Whitelist of safe names for eval context
SAFE_GLOBALS = {
    "__builtins__": {},
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "pow": pow, "int": int, "float": float,
    # math module functions
    "sqrt": math.sqrt, "ceil": math.ceil, "floor": math.floor,
    "log": math.log, "log2": math.log2, "log10": math.log10,
    "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "pi": math.pi, "e": math.e, "tau": math.tau,
    "factorial": math.factorial, "gcd": math.gcd,
    "degrees": math.degrees, "radians": math.radians,
    "hypot": math.hypot,
}


class MathEngine:
    """
    Safe expression evaluator using whitelisted builtins.
    Supports: basic arithmetic, trigonometry, logarithms, constants.
    """

    @staticmethod
    def evaluate(expression: str) -> Union[float, int, str]:
        """
        Evaluate a mathematical expression string.
        Returns result or error string.
        """
        # Sanitise: remove anything not in a safe character set
        clean = expression.strip()
        allowed = re.compile(r'^[\d\s\+\-\*/\(\)\.\^%,a-zA-Z_]+$')
        if not allowed.match(clean):
            return "Error: Invalid characters in expression."

        # Replace ^ with ** for power operator
        clean = clean.replace("^", "**")

        try:
            result = eval(clean, SAFE_GLOBALS, {})
            # Return int if it's a whole number
            if isinstance(result, float) and result.is_integer():
                return int(result)
            return result
        except ZeroDivisionError:
            return "Error: Division by zero."
        except (SyntaxError, NameError, TypeError) as e:
            return f"Error: {e}"
        except OverflowError:
            return "Error: Result too large."

    @staticmethod
    def format_result(result: Union[float, int, str]) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, int):
            return f"= {result:,}"
        return f"= {result:.10g}"
