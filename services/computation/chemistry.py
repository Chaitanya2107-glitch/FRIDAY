"""Neutral chemical formulas, exact atom conservation, approximate molar masses."""

from collections import Counter
import math
import re

import sympy as sp

from services.computation.engine import EngineResult

ELEMENTS = set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
               "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce "
               "Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn "
               "Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split())
# CIAAW Abridged Standard Atomic Weights 2024, central values only (g/mol).
# https://www.ciaaw.org/abridged-atomic-weights.htm
WEIGHTS = dict(zip(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Br Ag I Ba Pt Au Hg Pb U".split(),
    "1.0080 4.0026 6.94 9.0122 10.81 12.011 14.007 15.999 18.998 20.180 22.990 24.305 "
    "26.982 28.085 30.974 32.06 35.45 39.95 39.098 40.078 44.956 47.867 50.942 51.996 "
    "54.938 55.845 58.933 58.693 63.546 65.38 79.904 107.87 126.90 137.33 195.08 196.97 200.59 207.2 238.03".split(),
))
_SUBSCRIPTS = str.maketrans("\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089", "0123456789")


def formula(source: str) -> Counter:
    source = re.sub(r"\((?:s|l|g|aq)\)$", "", source.strip()).translate(_SUBSCRIPTS)
    if not source or len(source) > 120:
        raise ValueError("A neutral formula must contain 1-120 characters.")
    total = Counter()
    for part_index, part in enumerate(source.split("\u00b7")):
        multiplier = 1
        if part_index and (match := re.match(r"(\d+)", part)):
            multiplier, part = int(match[1]), part[match.end():]
        if not 1 <= multiplier <= 9999:
            raise ValueError("Hydrate multipliers must be between 1 and 9999.")
        tokens = re.findall(r"[A-Z][a-z]?|\d+|[()\[\]]", part)
        if "".join(tokens) != part or not tokens:
            raise ValueError("Use case-sensitive neutral formulas, groups and optional middle-dot hydrates.")
        index = 0

        def count() -> int:
            nonlocal index
            result = 1
            if index < len(tokens) and tokens[index].isdigit():
                result = int(tokens[index])
                index += 1
            if not 1 <= result <= 9999:
                raise ValueError("Atom/group counts must be between 1 and 9999.")
            return result

        def group(closing=None, depth=0) -> Counter:
            nonlocal index
            if depth > 8:
                raise ValueError("Formula nesting is limited to eight levels.")
            atoms = Counter()
            while index < len(tokens):
                token = tokens[index]
                index += 1
                if token in {"(", "["}:
                    nested = group(")" if token == "(" else "]", depth + 1)
                    scale = count()
                    atoms.update({element: number * scale for element, number in nested.items()})
                elif token in {")", "]"}:
                    if token != closing or not atoms:
                        raise ValueError("Unmatched or empty formula group.")
                    return atoms
                elif token in ELEMENTS:
                    atoms[token] += count()
                else:
                    raise ValueError(f"Unknown element or misplaced count: {token}.")
                if sum(atoms.values()) > 1000000:
                    raise ValueError("Formula atom counts are too large.")
            if closing or not atoms:
                raise ValueError("Unclosed or empty formula group.")
            return atoms

        atoms = group()
        total.update({element: number * multiplier for element, number in atoms.items()})
        if sum(total.values()) > 1000000:
            raise ValueError("Formula atom counts are too large.")
    return total


def compute(tail: str) -> EngineResult:
    if tail.lower().startswith("molar mass "):
        source = tail[11:].strip()
        atoms = formula(source)
        missing = set(atoms) - set(WEIGHTS)
        if missing:
            raise ValueError("No molar-mass weight in the local table for: " + ", ".join(sorted(missing)))
        mass = sum(sp.Rational(WEIGHTS[element]) * number for element, number in atoms.items())
        working = " + ".join(f"{number}*{WEIGHTS[element]} ({element})" for element, number in atoms.items())
        return EngineResult(True, "chemistry", f"M({source}) approximately {float(mass):.8g} g/mol", (working,),
                            ("Approximate CIAAW 2024 abridged standard weights; isotope/measurement uncertainty is not propagated.",),
                            {"atoms": dict(atoms), "molar_mass_g_per_mol": str(mass)})
    if not tail.lower().startswith("balance "):
        raise ValueError("Use: chemistry balance Fe + O2 -> Fe2O3, or chemistry molar mass Ca(OH)2.")
    source = tail[8:].strip().replace("\u2192", "->")
    if source.count("->") != 1:
        raise ValueError("Use exactly one -> between reactants and products.")
    left, right = ([item.strip() for item in side.split("+")] for side in source.split("->"))
    species = left + right
    if not left or not right or not 2 <= len(species) <= 12 or any(not item for item in species):
        raise ValueError("Use 2-12 nonempty neutral species, without supplied coefficients or charges.")
    counts = [formula(item) for item in species]
    elements = sorted(set().union(*counts))
    conservation = sp.Matrix([[atoms[element] * (1 if column < len(left) else -1)
                               for column, atoms in enumerate(counts)] for element in elements])
    basis = conservation.nullspace()
    if len(basis) != 1:
        raise ValueError("The reaction has no unique balancing ratio; check or reduce the listed species.")
    scale = sp.ilcm(*[value.q for value in basis[0]])
    coefficients = [int(value * scale) for value in basis[0]]
    if all(value < 0 for value in coefficients):
        coefficients = [-value for value in coefficients]
    if any(value <= 0 for value in coefficients):
        raise ValueError("All listed species must have strictly positive balancing coefficients.")
    divisor = math.gcd(*coefficients)
    coefficients = [value // divisor for value in coefficients]
    if conservation * sp.Matrix(coefficients) != sp.zeros(len(elements), 1):
        raise ValueError("Atom conservation verification failed.")
    terms = [f"{coefficient if coefficient != 1 else ''}{item}" for coefficient, item in zip(coefficients, species)]
    checks = []
    for element in elements:
        left_count = sum(coefficients[i] * counts[i][element] for i in range(len(left)))
        right_count = sum(coefficients[i] * counts[i][element] for i in range(len(left), len(species)))
        checks.append(f"{element}: {left_count} = {right_count} atoms")
    return EngineResult(True, "chemistry", " + ".join(terms[:len(left)]) + " -> " + " + ".join(terms[len(left):]),
                        tuple(checks), ("Conserves atoms; does not establish whether a reaction occurs or its conditions.",),
                        {"species": species, "coefficients": coefficients})
