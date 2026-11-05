"""Independent known answers, domain failures, isolation and procedural invariants."""

import json
import subprocess
import sys
import threading
from types import SimpleNamespace

import psutil
import pytest
import sympy as sp

from services.computation import engine
from services.computation.chemistry import formula
from services.computation.engine import calculate, evaluate
from services.computation.expressions import parse
from services.computation.stories import Action, generate, plan


@pytest.mark.parametrize("command,expected", [
    ("calculate 0.1 + 0.2", "3/10"),
    ("calculate 1/3 + 1/6", "1/2"),
    ("calculate 2^3^2", "512"),
    ("math simplify sin(x)^2 + cos(x)^2", "1"),
    ("math expand (x + 1)^3", "x**3 + 3*x**2 + 3*x + 1"),
    ("math factor x^2 - 9", "(x - 3)*(x + 3)"),
    ("differentiate x^3 + sin(x) wrt x", "3*x**2 + cos(x)"),
    ("differentiate x^4 wrt x order 2", "12*x**2"),
    ("integrate x^2 wrt x from 0 to 3", "9"),
    ("integrate x^2 wrt x from 3 to 0", "-9"),
    ("integrate 1/sqrt(x) wrt x from 0 to 1", "2"),
    ("integrate x^2 wrt x", "x**3/3 + C"),
    ("limit sin(x)/x as x -> 0", "1"),
    ("limit 1/x as x -> oo", "0"),
    ("solve x^2 - 5*x + 6 = 0 for x", "x in {2, 3}"),
    ("solve x^2 + 1 = 0 for x", "No real solutions."),
    ("solve 0 = 0 for x", "x: all real numbers"),
    ("vector dot [1,2,3]; [4,5,6]", "32"),
    ("vector cross [1,2,3]; [4,5,6]", "[-3, 6, -3]"),
    ("vector norm [3,4]", "5"),
    ("vector normalize [3,4]", "[3/5, 4/5]"),
    ("vector projection [2,3]; [1,0]", "[2, 0]"),
    ("vector angle [1,0]; [0,1]", "pi/2"),
    ("matrix determinant [[1,2],[3,4]]", "-2"),
    ("matrix inverse [[1,2],[3,4]]", "[[-2, 1], [3/2, -1/2]]"),
    ("matrix multiply [[1,2]]; [[3],[4]]", "[11]"),
    ("matrix solve [[2,1],[1,-1]]; [5,1]", "[2, 1]"),
    ("convert 36 km/h to m/s", "10 m/s"),
    ("convert 1 N to kg*m/s^2", "1 kg*m/s^2"),
    ("convert 180 deg to rad", "pi rad"),
    ("convert 25 C to F", "77 F"),
    ("convert 32 F to C", "0 C"),
    ("convert 1 L to m^3", "1/1000 m^3"),
    ("physics force mass=10 acceleration=3", "30 N"),
    ("physics kinetic mass=2 speed=3", "9 J"),
    ("physics potential mass=2 height=10 gravity=10", "200 J"),
    ("physics momentum mass=2 velocity=-3", "-6 kg*m/s"),
    ("physics ohm current=2 resistance=5", "10 V"),
    ("physics power voltage=12 current=2", "24 W"),
    ("physics wave frequency=50 wavelength=2", "100 m/s"),
    ("physics projectile speed=20 angle=45 gravity=10", "40 m"),
    ("chemistry balance Fe + O2 -> Fe2O3", "4Fe + 3O2 -> 2Fe2O3"),
    ("chemistry balance C2H6 + O2 -> CO2 + H2O", "2C2H6 + 7O2 -> 4CO2 + 6H2O"),
    ("chemistry balance Al + HCl -> AlCl3 + H2", "2Al + 6HCl -> 2AlCl3 + 3H2"),
    ("chemistry balance Ca(OH)2 + HCl -> CaCl2 + H2O", "Ca(OH)2 + 2HCl -> CaCl2 + 2H2O"),
    ("chemistry molar mass H2O", "M(H2O) approximately 18.015 g/mol"),
])
def test_known_answers(command, expected):
    result = evaluate(command)
    assert result.success
    assert result.value == expected or result.value.startswith(expected + " (")
    assert result.steps


def test_population_statistics_have_independent_reference_values():
    result = evaluate("stats [2,4,4,4,5,5,7,9]")
    assert result.value == "count = 8; mean = 5; median = 9/2; population variance = 4; population std = 2"


def test_ideal_gas_uses_si_volume_and_exact_defined_gas_constant():
    result = evaluate("physics gas moles=1 temperature=300 volume=0.025")
    assert "99773.5514178 Pa" in result.value
    assert "volume in m^3" in " ".join(result.assumptions)


def test_equation_retains_excluded_denominator_domain():
    result = evaluate("solve x/x = 1 for x")
    assert "all real numbers" not in result.value
    assert "0" in result.value and ("Interval" in result.value or "Complement" in result.value)
    result = evaluate("solve (x^2-1)/(x-1) = 2 for x")
    assert result.value == "No real solutions."


def test_principal_fractional_power_roots_are_domain_checked_and_verified():
    assert evaluate("solve x^(2/3)=1 for x").value == "x in {1}"
    assert evaluate("solve x^(1/3)=-1 for x").value == "No real solutions."
    assert evaluate("solve 2^x=8 for x").value == "x in {3}"


@pytest.mark.parametrize("command", [
    "calculate 1/0", "calculate log(0)", "calculate unknown + 1",
    "calculate __import__('os').system('echo unsafe')", "calculate (1).__class__",
    "calculate [x for x in [1]]", "calculate (lambda: 1)()", "calculate sin(x=1)",
    "calculate sqrt(1,2)", "calculate True", "calculate 0xFF", "calculate 1e101",
    "calculate 10^1000000", "calculate 2^(2^30)",
    "differentiate x^4 wrt x order 9", "integrate 1/x wrt x from -1 to 1",
    "integrate tan(x) wrt x from 0 to pi", "integrate 1/x^2 wrt x from 0 to 1",
    "integrate sqrt(x) wrt x from -1 to 1", "integrate x*y wrt x from 0 to 1",
    "limit 1/x as x -> 0", "limit 1/x as x -> 0 side right", "solve x + y = 2 for x",
    "limit 1/x as x -> sqrt(-1)", "limit x as x -> log(-1)", "solve 0^x=0 for x",
    "solve (-2)^x=4 for x", "integrate x^(1/3) wrt x from -1 to 1",
    "vector dot [1,2]; [1,2,3]", "vector cross [1,2]; [3,4]",
    "vector normalize [0,0]", "vector angle [0,0]; [1,0]", "vector projection [1,2]; [0,0]",
    "vector norm [x,2]", "matrix inverse [[1,2],[2,4]]", "matrix determinant [[1,2,3],[4,5,6]]",
    "matrix determinant [[1],[2,3]]", "matrix multiply [[1,2]]; [[1,2]]",
    "matrix solve [[1,2],[2,4]]; [1,2]", "stats []",
    "convert 3 kg to m", "convert -300 C to K", "convert 1 C/m to K/m",
    "convert -1 K^1 to K", "convert -1 K to K^1",
    "convert 2 unknown to m", "convert 2 m^100 to m", "physics force mass=-1 acceleration=2",
    "physics force mass=2", "physics force mass=2 acceleration=3 extra=1",
    "physics force mass=2 mass=3 acceleration=1", "physics gas moles=1 temperature=300 volume=0",
    "physics projectile speed=20 angle=100", "physics projectile speed=20 angle=45 gravity=0",
    "chemistry balance H2 -> O2", "chemistry balance H2 + O2 -> H2O + H2O2",
    "chemistry balance H2 + O2 -> H2O +", "chemistry molar mass Qq2",
    "chemistry molar mass Ca(OH", "chemistry molar mass H0", "chemistry molar mass ()",
    "chemistry molar mass 2H2O", "chemistry molar mass Tc", "chemistry molar mass H2O xyz",
])
def test_invalid_undefined_or_unsupported_inputs_are_not_solved(command):
    with pytest.raises((ValueError, SyntaxError, TypeError, ArithmeticError, NotImplementedError)):
        evaluate(command)


def test_ast_limits_and_nested_unsafe_nodes():
    for source in ("+".join(["x"] * 100), "sin(" * 20 + "x" + ")" * 20,
                   "[1][0]", "{'x': 1}", "sum([1,2])", "1" * 41):
        with pytest.raises((ValueError, SyntaxError)):
            parse(source)


def test_nested_groups_hydrates_and_unicode_subscripts():
    assert formula("K4[Fe(CN)6]") == {"K": 4, "Fe": 1, "C": 6, "N": 6}
    assert formula("CuSO4\u00b75H2O") == {"Cu": 1, "S": 1, "O": 9, "H": 10}
    assert formula("H\u2082O") == {"H": 2, "O": 1}
    assert formula("H2O(l)") == {"H": 2, "O": 1}


def test_balancing_is_independently_verified_from_result_coefficients():
    result = evaluate("chemistry balance KMnO4 + HCl -> KCl + MnCl2 + H2O + Cl2")
    assert result.details["coefficients"] == [2, 16, 2, 2, 8, 5]
    assert all(" = " in check for check in result.steps)


@pytest.mark.parametrize("genre", ["scifi", "fantasy", "mystery"])
def test_story_plans_are_reproducible_causal_and_reach_goal(genre):
    endings, paths = set(), set()
    for seed in range(24):
        result = generate(f"{genre} seed={seed} hero=Mira")
        assert result == generate(f"{genre} seed={seed} hero=Mira")
        details = result.details
        state = set(details["initial"])
        assert not set(details["goal"]) <= state
        for step in details["plan"]:
            assert set(step["before"]) == state
            assert set(step["requires"]) <= state
            state = state - set(step["removes"]) | set(step["adds"])
            assert set(step["after"]) == state
        assert set(details["goal"]) <= state == set(details["final"])
        assert "Mira" in result.value
        endings.add(details["objective"])
        paths.add(tuple(step["action"] for step in details["plan"]))
    assert len(endings) == 3 and len(paths) > 3


def test_story_planner_fails_unreachable_goals():
    action = Action("find", frozenset({"outside"}), frozenset({"key"}), frozenset(), 1, "Found a key.")
    with pytest.raises(ValueError, match="No complete story"):
        plan(frozenset({"home"}), frozenset({"key"}), [action])


def test_custom_hero_and_ally_remain_distinct():
    for seed in range(24):
        result = generate(f"fantasy seed={seed} hero=Ren")
        assert "Ren found Ren" not in result.value
        assert "Ren said" not in result.value


@pytest.mark.parametrize("payload", ["seed=-1", "seed=4294967296", "seed=1 seed=2", "genre=unknown", "hero=", "about ", "about x\ny"])
def test_story_input_validation(payload):
    with pytest.raises(ValueError):
        generate(payload)


@pytest.mark.parametrize("command,expected", [
    ("calculate 1/3+1/6", "1/2"),
    ("chemistry balance H2 + O2 -> H2O", "2H2 + O2 -> 2H2O"),
    ("story fantasy seed=42 hero=Mira", "Mira"),
])
def test_real_isolated_worker(command, expected):
    result = calculate(command)
    assert result.success and expected in result.value


def test_public_boundary_errors_do_not_fall_through():
    for command in (None, "", "x" * 1601, "calculate __import__('os')"):
        result = calculate(command)
        assert not result.success and result.render().startswith("Calculation unavailable:")


def test_busy_engine_refuses_unbounded_queue(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(engine, "_slots", slots)
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: pytest.fail("busy engine started a child"))
    assert "busy" in calculate("calculate 2+2").value


def test_real_timeout_kills_and_reaps_child_and_releases_slot(monkeypatch):
    real_run = subprocess.run
    child_pids = []

    def slow_worker(*args, **kwargs):
        try:
            return real_run([args[0][0], "-I", "-B", "-c",
                             "import os,time; print(os.getpid(),flush=True); time.sleep(30)"],
                            capture_output=True, text=True, timeout=1, env=kwargs["env"],
                            creationflags=kwargs["creationflags"])
        except subprocess.TimeoutExpired as error:
            child_pids.append(int(error.output))
            raise

    monkeypatch.setattr(engine.subprocess, "run", slow_worker)
    monkeypatch.setattr(engine, "_slots", threading.BoundedSemaphore(1))
    assert "was stopped" in calculate("calculate 1+1").value
    assert child_pids and not psutil.pid_exists(child_pids[0])
    assert engine._slots.acquire(blocking=False)
    engine._slots.release()


@pytest.mark.parametrize("response", ["bad json", "[]", '{"success":1,"value":"bad","domain":"engine"}',
                                      '{"success":true,"value":"bad","domain":"engine","steps":[1]}'])
def test_invalid_worker_protocol_is_unavailable(monkeypatch, response):
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=response))
    assert not calculate("calculate 2+2").success
