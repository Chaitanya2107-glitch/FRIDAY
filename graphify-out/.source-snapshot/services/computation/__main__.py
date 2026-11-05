"""python -m services.computation 'calculate 1/3 + 1/6' [--json] | --demo"""

import argparse

from services.computation.engine import calculate, encode

DEMO = (
    "calculate (1/3 + 1/6)^2",
    "math factor x^4 - 1",
    "differentiate x^3 + sin(x) wrt x",
    "integrate x^2 wrt x from 0 to 3",
    "limit sin(x)/x as x -> 0",
    "vector cross [1,2,3]; [4,5,6]",
    "matrix solve [[2,1],[1,-1]]; [5,1]",
    "convert 36 km/h to m/s",
    "physics projectile speed=20 angle=45",
    "physics gas moles=1 temperature=300 volume=0.025",
    "chemistry balance C2H6 + O2 -> CO2 + H2O",
    "chemistry molar mass Ca(OH)2",
    "stats [2,4,4,4,5,5,7,9]",
    "story fantasy seed=42 hero=Mira",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="FRIDAY's offline mathematical and procedural engine")
    parser.add_argument("command", nargs="*", help="Command text; quote formulas and semicolons in your shell")
    parser.add_argument("--json", action="store_true", help="Structured result including story planning trace")
    parser.add_argument("--demo", action="store_true", help="Run reproducible math, science and story examples")
    args = parser.parse_args()
    queries = DEMO if args.demo else (" ".join(args.command) or "engine help",)
    success = True
    for query in queries:
        result = calculate(query)
        success = success and result.success
        print(encode(result) if args.json else f"> {query}\n{result.render()}\n")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
