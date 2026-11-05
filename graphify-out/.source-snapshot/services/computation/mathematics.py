"""Exact arithmetic, calculus, linear algebra and descriptive statistics."""

import re

import sympy as sp
from sympy.calculus.util import continuous_domain

from services.computation.engine import EngineResult
from services.computation.expressions import finite, matrix, parse, variable, vector


def real_domain(expr, var):
    domain = continuous_domain(expr, var, sp.S.Reals)
    for power in expr.atoms(sp.Pow):
        base, exponent = power.args
        exponent = sp.simplify(exponent)
        if exponent.has(var) and base.is_positive is not True:
            raise ValueError("Variable exponents require a provably positive base in real-domain solving/integration.")
        if exponent.is_Rational and not exponent.is_Integer and base.has(var):
            condition = base > 0 if exponent < 0 else base >= 0
            domain = domain.intersect(sp.solve_univariate_inequality(condition, var, relational=False))
    return domain


def answer(domain: str, value, *steps: str, assumptions=()) -> EngineResult:
    if isinstance(value, sp.MatrixBase):
        for entry in value:
            finite(entry)
        rendered = str(value.tolist() if value.cols > 1 else list(value))
    elif isinstance(value, sp.Expr):
        finite(value)
        if value.has(sp.Integral, sp.Derivative, sp.Limit):
            raise ValueError("The symbolic operation remains unevaluated; no solved result is available.")
        rendered = str(value)
        if value.is_number and not value.is_Integer:
            rendered += f" (approximately {sp.N(value, 12)})"
    else:
        rendered = str(value)
    return EngineResult(True, domain, rendered, tuple(steps), tuple(assumptions))


def compute_math(query: str) -> EngineResult:
    if query.startswith("math "):
        query = query[5:].strip()
    head, _, tail = query.partition(" ")
    if head in {"calculate", "simplify", "expand", "factor"}:
        value = finite(parse(tail))
        operation = {"calculate": lambda v: v, "simplify": sp.simplify,
                     "expand": sp.expand, "factor": sp.factor}[head]
        return answer("algebra", operation(value), f"{head}: {value}",
                      assumptions=("Exact decimal/rational arithmetic; angles in radians; symbols are real.",))
    if head == "differentiate":
        match = re.fullmatch(r"(.+?)\s+(?:wrt|with respect to)\s+([a-z])(?:\s+order\s+(\d+))?", tail)
        if not match:
            raise ValueError("Use: differentiate x^3 + sin(x) wrt x [order 2].")
        expr, var, order = finite(parse(match[1])), variable(match[2]), int(match[3] or 1)
        if not 1 <= order <= 8:
            raise ValueError("Derivative order must be between 1 and 8.")
        return answer("calculus", sp.diff(expr, var, order), f"d^{order}/d{var}^{order} ({expr})",
                      assumptions=("Other symbols are constants; real variables; radians.",))
    if head == "integrate":
        match = re.fullmatch(r"(.+?)\s+(?:wrt|with respect to)\s+([a-z])(?:\s+from\s+(.+?)\s+to\s+(.+))?", tail)
        if not match:
            raise ValueError("Use: integrate x^2 wrt x [from 0 to 1].")
        expr, var = finite(parse(match[1], preserve=True)), variable(match[2])
        if match[3] is not None:
            low, high = finite(parse(match[3]), numeric=True), finite(parse(match[4]), numeric=True)
            if expr.free_symbols - {var}:
                raise ValueError("Definite integrals require numeric parameters and bounds.")
            if low == high:
                return answer("calculus", sp.S.Zero, "The integration interval has zero width.")
            interval = sp.Interval.open(min(low, high), max(low, high))
            domain = real_domain(expr, var)
            if interval.is_subset(domain) is not True:
                raise ValueError("The integrand is not continuous and real throughout the open interval; split or reformulate it.")
            result = sp.integrate(expr, (var, low, high))
            return answer("calculus", result, f"Integral of {expr} d{var} from {low} to {high}",
                          assumptions=("Real interval; no principal-value interpretation.",))
        result = sp.integrate(expr, var)
        if result.has(sp.Integral) or sp.simplify(sp.diff(result, var) - expr) != 0:
            raise ValueError("A verified symbolic antiderivative was not found.")
        return answer("calculus", f"{result} + C", f"Integrate {expr} with respect to {var}",
                      f"Derivative check: d/d{var} ({result}) = {expr}",
                      assumptions=("C is an arbitrary integration constant; valid where the expression is differentiable.",))
    if head == "limit":
        match = re.fullmatch(r"(.+?)\s+as\s+([a-z])\s*->\s*(.+?)(?:\s+side\s+(left|right))?", tail)
        if not match:
            raise ValueError("Use: limit sin(x)/x as x -> 0 [side left|right].")
        expr, var, point = finite(parse(match[1])), variable(match[2]), parse(match[3], infinity=True)
        if point.free_symbols:
            raise ValueError("The limit point must be numeric or +/-oo.")
        if point not in {sp.oo, -sp.oo}:
            finite(point, numeric=True)
        if match[4] or point in {sp.oo, -sp.oo}:
            result = sp.limit(expr, var, point, dir="-" if match[4] == "left" else "+")
        else:
            left, right = sp.limit(expr, var, point, dir="-"), sp.limit(expr, var, point, dir="+")
            if left != right:
                raise ValueError(f"The two-sided limit does not exist: left {left}, right {right}.")
            result = left
        return answer("calculus", result, f"Limit of {expr} as {var} -> {point}",
                      assumptions=(f"{match[4] or 'Two-sided'} limit; real variable.",))
    if head == "solve":
        match = re.fullmatch(r"(.+?)\s+for\s+([a-z])", tail)
        if not match or match[1].count("=") > 1:
            raise ValueError("Use: solve x^2 - 5*x + 6 = 0 for x.")
        sides = match[1].split("=")
        lhs = finite(parse(sides[0], preserve=True))
        rhs = finite(parse(sides[1], preserve=True)) if len(sides) == 2 else sp.S.Zero
        var = variable(match[2])
        if (lhs - rhs).free_symbols - {var}:
            raise ValueError("Substitute other symbols before solving this one-variable equation.")
        domain = real_domain(lhs, var).intersect(real_domain(rhs, var))
        roots = sp.solveset(lhs - rhs, var, domain=domain)
        if roots.has(sp.ConditionSet):
            raise ValueError("A complete real solution set was not found.")
        if isinstance(roots, sp.FiniteSet):
            verified = []
            for root in roots:
                residual = sp.simplify(lhs.subs(var, root) - rhs.subs(var, root))
                if residual == 0:
                    verified.append(root)
                elif residual.is_zero is None:
                    raise ValueError("A candidate solution could not be verified by substitution.")
            roots = sp.FiniteSet(*verified)
        if roots == sp.S.EmptySet:
            rendered = "No real solutions."
        elif roots == sp.S.Reals:
            rendered = f"{var}: all real numbers"
        else:
            rendered = f"{var} in {roots}"
        return answer("algebra", rendered, f"Solve {lhs} = {rhs}",
                      assumptions=("Real-valued component domains; fractional powers use the principal branch.",))
    if head == "vector":
        return _vector(tail)
    if head == "matrix":
        return _matrix(tail)
    if head == "stats":
        values = list(vector(tail))
        n = len(values)
        mean = sum(values) / n
        ordered = sorted(values)
        median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
        variance = sum((v - mean) ** 2 for v in values) / n
        return answer("statistics", f"count = {n}; mean = {mean}; median = {median}; "
                      f"population variance = {variance}; population std = {sp.sqrt(variance)}",
                      "Mean = sum(x)/n; population variance = sum((x - mean)^2)/n",
                      assumptions=("Descriptive population statistics; at most 16 finite real values.",))
    # A bare expression is allowed only inside the explicit math namespace.
    if query and head not in {"math", "engine"}:
        return answer("arithmetic", finite(parse(query)), "Evaluate using exact arithmetic.")
    raise ValueError('Use "engine help" for supported operations.')


def _vector(tail: str) -> EngineResult:
    operation, _, payload = tail.partition(" ")
    parts = payload.split(";")
    if operation in {"norm", "normalize"} and len(parts) == 1:
        a = vector(parts[0])
        norm = sp.sqrt(a.dot(a))
        if operation == "normalize" and norm == 0:
            raise ValueError("A zero vector cannot be normalized.")
        return answer("vectors", norm if operation == "norm" else a / norm, "norm(a) = sqrt(a dot a)")
    if len(parts) != 2:
        raise ValueError("Use: vector dot|cross|angle|add|projection [1,2,3]; [4,5,6].")
    a, b = vector(parts[0]), vector(parts[1])
    if a.rows != b.rows:
        raise ValueError("Vector dimensions must match.")
    if operation == "dot":
        return answer("vectors", a.dot(b), "Dot product = sum(a_i*b_i)")
    if operation == "cross":
        if a.rows != 3:
            raise ValueError("Cross products require two 3D vectors.")
        return answer("vectors", a.cross(b), "Cross product = [ay*bz-az*by, az*bx-ax*bz, ax*by-ay*bx]")
    if operation == "add":
        return answer("vectors", a + b, "Add corresponding vector components.")
    if operation == "projection":
        if b.dot(b) == 0:
            raise ValueError("Cannot project onto a zero vector.")
        return answer("vectors", (a.dot(b) / b.dot(b)) * b, "proj_b(a) = (a dot b)/(b dot b) * b")
    if operation == "angle":
        norm_product = sp.sqrt(a.dot(a) * b.dot(b))
        if norm_product == 0:
            raise ValueError("The angle of a zero vector is undefined.")
        radians = sp.acos(a.dot(b) / norm_product)
        return answer("vectors", radians, f"acos((a dot b)/(|a|*|b|)); degrees = {sp.N(radians * 180 / sp.pi, 10)}",
                      assumptions=("Result in radians.",))
    raise ValueError("Supported vector operations: dot, cross, add, norm, normalize, angle, projection.")


def _matrix(tail: str) -> EngineResult:
    operation, _, payload = tail.partition(" ")
    parts = payload.split(";")
    a = matrix(parts[0])
    if operation in {"determinant", "inverse"} and len(parts) == 1:
        if a.rows != a.cols:
            raise ValueError("A square matrix is required.")
        determinant = a.det()
        if operation == "inverse" and determinant == 0:
            raise ValueError("A singular matrix has no inverse.")
        return answer("matrices", determinant if operation == "determinant" else a.inv(),
                      f"Matrix shape: {a.rows}x{a.cols}; determinant = {determinant}")
    if operation == "transpose" and len(parts) == 1:
        return answer("matrices", a.T, "Swap rows and columns.")
    if operation == "multiply" and len(parts) == 2:
        b = matrix(parts[1])
        if a.cols != b.rows:
            raise ValueError("Matrix multiplication requires A columns = B rows.")
        return answer("matrices", a * b, "C_ij = sum_k A_ik * B_kj")
    if operation == "solve" and len(parts) == 2:
        b = vector(parts[1])
        if a.rows != a.cols or a.rows != b.rows or a.det() == 0:
            raise ValueError("Use an invertible square matrix and a matching right-hand-side vector.")
        result = a.inv() * b
        return answer("matrices", result, "Solve A*x = b with exact rational arithmetic.",
                      f"Substitution check A*x = {list(a * result)}")
    raise ValueError("Use matrix determinant|inverse|transpose A, multiply A; B, or solve A; [b1,b2].")
