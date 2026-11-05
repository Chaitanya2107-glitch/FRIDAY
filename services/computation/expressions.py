"""A small mathematical AST, constructed directly: user text is never executed."""

import ast
import math
import re

import sympy as sp

SYMBOLS = {name: sp.Symbol(name, real=True) for name in "xyz tabcuvwn".replace(" ", "")}
CONSTANTS = {"pi": sp.pi, "e": sp.E, "E": sp.E, "oo": sp.oo}
FUNCTIONS = {name: getattr(sp, name) for name in (
    "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh",
    "exp", "log", "sqrt", "Abs",
)}
FUNCTIONS.update({"ln": sp.log, "abs": sp.Abs})


def variable(name: str) -> sp.Symbol:
    if name not in SYMBOLS:
        raise ValueError("Variable must be one of: " + ", ".join(SYMBOLS))
    return SYMBOLS[name]


def parse(source: str, *, lists: bool = False, infinity: bool = False, preserve: bool = False):
    source = source.strip().replace("^", "**").replace("\u2212", "-").replace("\u00d7", "*")
    if not source or len(source) > 512:
        raise ValueError("Expressions must contain 1-512 characters.")
    # Reject enormous decimal exponents before constructing an exact rational.
    for match in re.finditer(r"\d(?:[\d.]*)(?:[eE]([+-]?\d+))?", source):
        if len(match[0]) > 40 or (match[1] and abs(int(match[1])) > 100):
            raise ValueError("Numeric literals are too large (40 digits; scientific exponent at most 100).")
    tree = ast.parse(source, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 160:
        raise ValueError("Too many expression nodes; split the calculation.")

    def visit(node, depth=0):
        if depth > 16:
            raise ValueError("Expression nesting is limited to 16 levels.")
        child = lambda item: visit(item, depth + 1)
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            if isinstance(node.value, float) and not math.isfinite(node.value):
                raise ValueError("Nonfinite numeric literals are not supported.")
            literal = ast.get_source_segment(source, node)
            if not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", literal or ""):
                raise ValueError("Use ordinary decimal numeric literals.")
            return sp.Rational(literal)
        if isinstance(node, ast.Name):
            if node.id in SYMBOLS:
                return SYMBOLS[node.id]
            if node.id in CONSTANTS and (infinity or node.id != "oo"):
                return CONSTANTS[node.id]
            raise ValueError(f"Unknown symbol: {node.id}.")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = child(node.operand)
            require_scalar(value)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            left, right = child(node.left), child(node.right)
            require_scalar(left)
            require_scalar(right)
            if isinstance(node.op, ast.Pow):
                if right.is_number and (right.is_real is not True or abs(right) > 1000):
                    raise ValueError("Numeric powers are limited to absolute exponent 1000.")
                if left.is_Rational and right.is_Integer and abs(right) * max(
                        int(left.p).bit_length(), int(left.q).bit_length()) > 16000:
                    raise ValueError("The integer power result would be too large.")
                return sp.Pow(left, right, evaluate=not preserve)
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("Division by zero is undefined.")
                return sp.Mul(left, sp.Pow(right, -1, evaluate=not preserve), evaluate=not preserve)
            if isinstance(node.op, ast.Add):
                return sp.Add(left, right, evaluate=not preserve)
            if isinstance(node.op, ast.Sub):
                return sp.Add(left, sp.Mul(-1, right, evaluate=not preserve), evaluate=not preserve)
            return sp.Mul(left, right, evaluate=not preserve)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS:
            if node.keywords or len(node.args) != 1:
                raise ValueError("Math functions take exactly one positional argument.")
            value = child(node.args[0])
            require_scalar(value)
            return FUNCTIONS[node.func.id](value, evaluate=not preserve)
        if lists and isinstance(node, (ast.List, ast.Tuple)) and 1 <= len(node.elts) <= 32:
            return [child(item) for item in node.elts]
        raise ValueError("Use only numbers, supported symbols/functions, + - * / ^ and parentheses.")

    value = visit(tree.body)
    if not lists:
        require_scalar(value)
    return value


def require_scalar(value) -> None:
    if not isinstance(value, sp.Expr):
        raise ValueError("A scalar expression is required here.")


def finite(value, *, numeric=False):
    require_scalar(value)
    if value.has(sp.nan, sp.zoo, sp.oo, -sp.oo) or value.is_finite is False:
        raise ValueError("The result is undefined or divergent.")
    if numeric and (value.free_symbols or value.is_real is not True or value.is_finite is not True):
        raise ValueError("A finite real number is required.")
    return value


def vector(source: str) -> sp.Matrix:
    values = parse(source, lists=True)
    if not isinstance(values, list) or not 1 <= len(values) <= 16 or any(isinstance(v, list) for v in values):
        raise ValueError("Use a vector of 1-16 scalar entries, e.g. [1,2,3].")
    return sp.Matrix([finite(v, numeric=True) for v in values])


def matrix(source: str) -> sp.Matrix:
    rows = parse(source, lists=True)
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 6
            or not all(isinstance(row, list) and 1 <= len(row) <= 6 for row in rows)
            or len({len(row) for row in rows}) != 1):
        raise ValueError("Use a rectangular matrix of at most 6x6 entries: [[1,2],[3,4]].")
    return sp.Matrix([[finite(v, numeric=True) for v in row] for row in rows])
