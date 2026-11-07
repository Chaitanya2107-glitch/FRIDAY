"""Bounded arithmetic AST; optional SymPy uses FRIDAY's existing safe worker."""
import ast
import importlib.util
import math
import operator
import re

FUNCTIONS = {'sqrt': math.sqrt, 'abs': abs, 'sin': math.sin, 'cos': math.cos,
             'tan': math.tan, 'log': math.log, 'ln': math.log, 'exp': math.exp}
OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.Pow: operator.pow}
SYMBOLS = set('xyzabcuvwn')


def installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def normalize(text: str) -> str:
    text = text.strip().replace('^', '**').replace('−', '-').replace('×', '*').replace('÷', '/')
    return re.sub(r'(\d|\))\s*([xyzabcuvwn]|\()', r'\1*\2', text)


def tree(text: str, symbolic=False):
    source = normalize(text)
    if len(source) > 160 or '__' in source:
        raise ValueError('Unsupported expression.')
    root = ast.parse(source, mode='eval')
    if sum(1 for _ in ast.walk(root)) > 64:
        raise ValueError('Expression too large.')

    def check(node, depth=0):
        if depth > 12:
            raise ValueError('Expression too deep.')
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if not math.isfinite(node.value) or abs(node.value) > 1e15:
                raise ValueError('Number too large.')
        elif isinstance(node, ast.Name) and (node.id in ('pi', 'e') or symbolic and node.id in SYMBOLS):
            pass
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            check(node.operand, depth + 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            check(node.left, depth + 1)
            check(node.right, depth + 1)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in FUNCTIONS and len(node.args) == 1 and not node.keywords):
            check(node.args[0], depth + 1)
        else:
            raise ValueError('Unsupported expression.')
    check(root.body)
    return root.body


def safe_arithmetic(text: str) -> str:
    def visit(node):
        if isinstance(node, ast.Constant):
            value = node.value
        elif isinstance(node, ast.Name):
            value = {'pi': math.pi, 'e': math.e}[node.id]
        elif isinstance(node, ast.UnaryOp):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.Call):
            value = FUNCTIONS[node.func.id](visit(node.args[0]))
        else:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError('Power too large.')
            value = OPERATORS[type(node.op)](left, right)
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e30:
            raise ValueError('Result too large or not real.')
        return value
    return format(visit(tree(text)), '.12g')


def equation(text: str) -> str | None:
    if text.count('=') != 1:
        return None
    names = set()
    for side in text.split('='):
        root = tree(side, symbolic=True)
        names.update(n.id for n in ast.walk(root) if isinstance(n, ast.Name) and n.id in SYMBOLS)
    return next(iter(names)) if len(names) == 1 else None


def math_score(text: str, symbolic: bool) -> float:
    # Ambiguous dates, telephone numbers, versions, amounts and bare literals win
    # over arithmetic. A subtraction requires spaces; other operators are clear.
    if (not text or len(text) > 160 or re.search(r'[$€£₹¥,:;\[\]{}\'"_]', text)
            or re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text.strip())
            or re.fullmatch(r'\+?\d[\d() .-]*\d', text.strip()) and not re.search(r'\s-\s', text)
            or re.search(r'\d+\.\d+\.\d+', text)
            or re.fullmatch(r'\d{1,4}[-/]\d{1,2}[-/]\d{1,4}', text)):
        return 0.0
    try:
        if '=' in text:
            return .97 if symbolic and equation(text) else 0.0
        root = tree(text)
        if not isinstance(root, (ast.BinOp, ast.Call)):
            return 0.0
        if isinstance(root, ast.BinOp) and isinstance(root.op, ast.Sub) and not re.search(r'\s-\s', text):
            return 0.0
        safe_arithmetic(text)
        return .94
    except Exception:
        return 0.0


class MathActions:
    def __init__(self, api):
        self.api = api
        self.has_sympy = installed('sympy')

    def symbolic(self):
        return self.has_sympy or self.api.get_service('math_engine') is not None

    def run(self, text: str) -> str:
        variable = equation(text) if '=' in text else None
        command = f'solve {normalize(text)} for {variable}' if variable else f'calculate {normalize(text)}'
        service = self.api.get_service('math_engine')
        if service is not None:
            # Providers are trusted in-process code and must keep this contract offline.
            if hasattr(service, 'calculate'):
                result = service.calculate(command)
            else:
                result = getattr(service, 'solve' if variable else 'evaluate')(text)
            if isinstance(result, str):
                return result
            if hasattr(result, 'render'):
                if getattr(result, 'success', True) is not True:
                    raise ValueError('Local math service unavailable.')
                return result.render()
            if isinstance(result, dict) and result.get('ok', result.get('success', True)):
                return str(result.get('value', result.get('text', '')))
            raise ValueError('Local math service unavailable.')
        if self.has_sympy:
            from services.computation.engine import calculate
            result = calculate(command)
            if not result.success:
                raise ValueError('Calculation unavailable.')
            return result.render()
        if variable:
            raise ValueError('Solving needs a local math engine.')
        return safe_arithmetic(text)

    def preview(self, text: str) -> str:
        if '=' not in text:
            return safe_arithmetic(text)
        # Only a small linear polynomial is cheap enough for a passive preview.
        if self.has_sympy and len(text) <= 60 and not re.search(r'[A-Z^/]|\*\*|[a-z]{2}', text):
            from services.computation.expressions import parse
            from sympy import Poly
            var = equation(text)
            left, right = (parse(normalize(side)) for side in text.split('='))
            symbol = next(iter((left - right).free_symbols))
            polynomial = Poly(left - right, symbol)
            if polynomial.degree() == 1:
                a, b = polynomial.all_coeffs()
                return f'{var} = {-b / a}'
        return 'Solve with the local math engine.'
