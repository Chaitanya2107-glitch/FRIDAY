"""Dimension-checked units and a small explicit catalog of idealized SI formulas."""

import re

import sympy as sp

from services.computation.engine import EngineResult
from services.computation.expressions import finite, parse
from services.computation.mathematics import answer

# Dimensions: length, mass, time, current, temperature, amount, plane angle.
_DIMENSIONS = {name: tuple(int(i == j) for i in range(7))
               for j, name in enumerate(("m", "kg", "s", "A", "K", "mol", "rad"))}
UNITS = {name: (sp.S.One, dimension) for name, dimension in _DIMENSIONS.items()}


def _unit(name, scale, dimension):
    UNITS[name] = (sp.Rational(scale), dimension)


for _name, _scale in {"mm": "0.001", "cm": "0.01", "km": "1000", "in": "0.0254", "ft": "0.3048", "mi": "1609.344"}.items():
    _unit(_name, _scale, _DIMENSIONS["m"])
for _name, _scale in {"g": "0.001", "mg": "0.000001", "lb": "0.45359237"}.items():
    _unit(_name, _scale, _DIMENSIONS["kg"])
for _name, _scale in {"ms": "0.001", "min": "60", "h": "3600", "day": "86400"}.items():
    _unit(_name, _scale, _DIMENSIONS["s"])
for _name, _scale, _dimension in (
        ("N", "1", (1, 1, -2, 0, 0, 0, 0)), ("J", "1", (2, 1, -2, 0, 0, 0, 0)),
        ("W", "1", (2, 1, -3, 0, 0, 0, 0)), ("Pa", "1", (-1, 1, -2, 0, 0, 0, 0)),
        ("kPa", "1000", (-1, 1, -2, 0, 0, 0, 0)), ("bar", "100000", (-1, 1, -2, 0, 0, 0, 0)),
        ("atm", "101325", (-1, 1, -2, 0, 0, 0, 0)), ("L", "0.001", (3, 0, 0, 0, 0, 0, 0)),
        ("mL", "0.000001", (3, 0, 0, 0, 0, 0, 0)), ("Hz", "1", (0, 0, -1, 0, 0, 0, 0)),
        ("V", "1", (2, 1, -3, -1, 0, 0, 0)), ("ohm", "1", (2, 1, -3, -2, 0, 0, 0)),
        ("kJ", "1000", (2, 1, -2, 0, 0, 0, 0))):
    _unit(_name, _scale, _dimension)
UNITS["deg"] = (sp.pi / 180, _DIMENSIONS["rad"])


def unit_expression(source: str):
    if len(source) > 60:
        raise ValueError("Unit expressions are limited to 60 characters.")
    tokens = re.split(r"([*/])", source.strip())
    scale, dimensions, sign = sp.S.One, [0] * 7, 1
    for index, token in enumerate(tokens):
        if index % 2:
            sign = -1 if token == "/" else 1
            continue
        match = re.fullmatch(r"([A-Za-z]+)(?:\^(-?\d+))?", token)
        if not match or match[1] not in UNITS:
            raise ValueError("Unknown unit. Use SI units or engine help; unit names are case-sensitive.")
        power = int(match[2] or 1) * sign
        if abs(power) > 8:
            raise ValueError("Unit exponents must be between -8 and 8.")
        factor, dimension = UNITS[match[1]]
        scale *= factor ** power
        dimensions = [old + power * value for old, value in zip(dimensions, dimension)]
    return scale, tuple(dimensions)


def convert(tail: str) -> EngineResult:
    match = re.fullmatch(r"(.+?)\s+(\S+)\s+to\s+(\S+)", tail)
    if not match:
        raise ValueError("Use: convert 36 km/h to m/s, or convert 25 C to F.")
    value, source, target = finite(parse(match[1]), numeric=True), match[2], match[3]
    temperatures = {"C", "F", "K"}
    if source in temperatures and target in temperatures:
        kelvin = value if source == "K" else value + sp.Rational("273.15") if source == "C" else (value - 32) * 5 / 9 + sp.Rational("273.15")
        if kelvin < 0:
            raise ValueError("Absolute temperature cannot be below zero kelvin.")
        result = kelvin if target == "K" else kelvin - sp.Rational("273.15") if target == "C" else (kelvin - sp.Rational("273.15")) * 9 / 5 + 32
        return answer("units", f"{sp.simplify(result)} {target}", f"Convert through kelvin: {kelvin} K",
                      assumptions=("Absolute temperatures, not temperature differences.",))
    source_scale, source_dim = unit_expression(source)
    target_scale, target_dim = unit_expression(target)
    if source_dim != target_dim:
        raise ValueError("Incompatible dimensions; these units cannot be converted.")
    if source_dim == _DIMENSIONS["K"] and value * source_scale < 0:
        raise ValueError("Absolute temperature cannot be below zero kelvin.")
    result = sp.simplify(value * source_scale / target_scale)
    return answer("units", f"{result} {target} (approximately {sp.N(result, 12)} {target})",
                  f"{value} * ({source_scale}) / ({target_scale})", assumptions=("Unit dimensions match.",))


def physics(tail: str) -> EngineResult:
    name, _, payload = tail.partition(" ")
    parameters = {}
    for token in payload.split():
        match = re.fullmatch(r"([a-z]+)=(\S+)", token)
        if not match or match[1] in parameters:
            raise ValueError("Use distinct name=value parameters without spaces inside values.")
        parameters[match[1]] = finite(parse(match[2]), numeric=True)
    # Formula syntax is fixed data; all input values use the bounded expression AST.
    catalog = {
        "force": ({"mass", "acceleration"}, "F = mass * acceleration", "N"),
        "kinetic": ({"mass", "speed"}, "E = mass * speed^2 / 2", "J"),
        "potential": ({"mass", "height"}, "E = mass * gravity * height", "J"),
        "momentum": ({"mass", "velocity"}, "p = mass * velocity", "kg*m/s"),
        "ohm": ({"current", "resistance"}, "V = current * resistance", "V"),
        "power": ({"voltage", "current"}, "P = voltage * current", "W"),
        "wave": ({"frequency", "wavelength"}, "v = frequency * wavelength", "m/s"),
        "gas": ({"moles", "temperature", "volume"}, "P = n*R*T / V", "Pa"),
        "projectile": ({"speed", "angle"}, "R = speed^2*sin(2*angle)/gravity", "m"),
    }
    if name not in catalog:
        raise ValueError("Available physics formulas: " + ", ".join(catalog))
    required, formula_text, unit = catalog[name]
    optional = {"gravity"} if name in {"potential", "projectile"} else set()
    if not required <= parameters.keys() or parameters.keys() - required - optional:
        raise ValueError(f"{name} requires: {', '.join(sorted(required))}. Optional: {', '.join(sorted(optional)) or 'none'}.")
    positive = {"mass", "resistance", "frequency", "wavelength", "volume", "temperature", "gravity"}
    nonnegative = {"speed", "moles"}
    for parameter, value in parameters.items():
        if (parameter in positive and value <= 0) or (parameter in nonnegative and value < 0):
            raise ValueError(f"{parameter} must be {'positive' if parameter in positive else 'nonnegative'}.")
    p = parameters
    gravity = p.get("gravity", sp.Rational("9.80665"))
    working = [formula_text, "Inputs (SI): " + ", ".join(f"{key}={value}" for key, value in sorted(p.items()))]
    assumptions = ["SI input: kg, m, s, A, ohm, V, mol, K, Hz as applicable; projectile angle in degrees."]
    if name == "force":
        result = p["mass"] * p["acceleration"]
        assumptions.append("Newtonian mechanics; acceleration is a signed component.")
    elif name == "kinetic":
        result = p["mass"] * p["speed"] ** 2 / 2
        assumptions.append("Nonrelativistic kinetic energy.")
    elif name == "potential":
        result = p["mass"] * gravity * p["height"]
        assumptions.append("Constant gravity; height relative to a chosen zero.")
    elif name == "momentum":
        result = p["mass"] * p["velocity"]
        assumptions.append("Nonrelativistic, signed one-dimensional momentum.")
    elif name == "ohm":
        result = p["current"] * p["resistance"]
        assumptions.append("Ideal ohmic resistance.")
    elif name == "power":
        result = p["voltage"] * p["current"]
        assumptions.append("DC instantaneous electrical power; signed current convention.")
    elif name == "wave":
        result = p["frequency"] * p["wavelength"]
        assumptions.append("Phase speed v = f*lambda.")
    elif name == "gas":
        result = p["moles"] * sp.Rational("8.31446261815324") * p["temperature"] / p["volume"]
        working.append("R = 8.31446261815324 J/(mol*K)")
        assumptions.append("Ideal gas; volume in m^3, absolute temperature in K.")
    else:
        if not 0 <= p["angle"] <= 90:
            raise ValueError("Projectile angle must be between 0 and 90 degrees.")
        result = p["speed"] ** 2 * sp.sin(2 * p["angle"] * sp.pi / 180) / gravity
        assumptions.append("No air resistance; equal launch/landing height; constant gravity.")
    if name in {"potential", "projectile"}:
        working.append(f"gravity = {gravity} m/s^2")
    finite(result, numeric=True)
    return answer("physics", f"{result} {unit} (approximately {sp.N(result, 12)} {unit})",
                  *working, assumptions=assumptions)


def compute_science(head: str, tail: str) -> EngineResult:
    if head == "convert":
        return convert(tail)
    if head == "physics":
        return physics(tail)
    from services.computation.chemistry import compute
    return compute(tail)
