# FRIDAY's local computation engine

FRIDAY can calculate and generate procedural stories without a text-generation
model, API key or network connection. Use the examples below in chat, the Island,
Control Center or the existing Telegram chat. Voice uses the same command router;
speaking exact mathematical syntax depends on the existing transcription system.

Restart the backend once after this source update. This implementation does not
restart your running assistant. The standalone CLI works immediately:

```powershell
venv/Scripts/python.exe -B -m services.computation --demo
venv/Scripts/python.exe -B -m services.computation "integrate x^2 wrt x from 0 to 3"
venv/Scripts/python.exe -B -m services.computation "story fantasy seed=42 hero=Mira" --json
```

`engine help` lists every supported command. An explicit command returns either a
local result or a local error; it never falls through to an LLM. Responses identify
the provider as `local`, model as `computation_engine`, and tokens used as zero.
Optional speech still uses FRIDAY's configured transcription and speech services.

## Math

| Command | Expected result |
| --- | --- |
| `calculate 0.1 + 0.2` | `3/10`, exactly |
| `calculate (1/3 + 1/6)^2` | `1/4` |
| `math simplify sin(x)^2 + cos(x)^2` | `1` |
| `math factor x^2 - 9` | `(x - 3)*(x + 3)` |
| `math expand (x + 1)^3` | `x^3 + 3*x^2 + 3*x + 1` |
| `solve x^2 - 5*x + 6 = 0 for x` | `{2, 3}`, real solutions |
| `differentiate x^3 + sin(x) wrt x` | `3*x^2 + cos(x)` |
| `differentiate x^4 wrt x order 2` | `12*x^2` |
| `integrate x^2 wrt x` | `x^3/3 + C`, with derivative check |
| `integrate x^2 wrt x from 0 to 3` | `9` |
| `limit sin(x)/x as x -> 0` | `1` |
| `vector dot [1,2,3]; [4,5,6]` | `32` |
| `vector cross [1,2,3]; [4,5,6]` | `[-3,6,-3]` |
| `vector normalize [3,4]` | `[3/5,4/5]` |
| `vector projection [2,3]; [1,0]` | `[2,0]` |
| `matrix determinant [[1,2],[3,4]]` | `-2` |
| `matrix solve [[2,1],[1,-1]]; [5,1]` | `[2,1]`, with substitution check |
| `stats [2,4,4,4,5,5,7,9]` | mean `5`, population variance `4` |

Use `*` for multiplication, `^` or `**` for powers, and explicit parentheses.
Decimals become exact rational numbers. Functions: `sin`, `cos`, `tan`, `asin`,
`acos`, `atan`, `sinh`, `cosh`, `tanh`, `exp`, `log`/`ln`, `sqrt`, `abs`/`Abs`.
Constants: `pi`, `e`/`E`; `oo` is allowed as a limit point. Supported real symbols:
`x,y,z,t,a,b,c,u,v,w,n`. Math angles are radians. Solving returns real solution
sets and preserves excluded denominator domains. General symbolic operations can
be unsupported or exceed the time budget; these cases return an error.
Powers use the principal complex branch: `(-1)^(1/3)` is not a real cube root.
Real solving/integration restrict fractional-power components to nonnegative
bases, verify finite roots by substitution, and reject symbolic exponents unless
their base is provably positive.

Vectors also support `add`, `norm` and `angle`; matrices also support `inverse`,
`transpose` and `multiply`. Vectors/statistics accept up to 16 finite real values;
matrices accept at most 6x6 entries. Singular inverses, zero-vector angles,
incompatible dimensions and divergent results are rejected. Definite integrals
use finite numeric bounds and a continuous real open interval; split unsupported
intervals explicitly. No Cauchy principal value is silently substituted.

## Physics, units and chemistry

```text
convert 36 km/h to m/s
convert 1 N to kg*m/s^2
convert 25 C to F
physics force mass=10 acceleration=3
physics kinetic mass=2 speed=3
physics potential mass=2 height=10
physics momentum mass=2 velocity=-3
physics ohm current=2 resistance=5
physics power voltage=12 current=2
physics wave frequency=50 wavelength=2
physics projectile speed=20 angle=45
physics gas moles=1 temperature=300 volume=0.025
chemistry balance C2H6 + O2 -> CO2 + H2O
chemistry molar mass Ca(OH)2
```

Physics is a named formula catalog with explicit assumptions, not an arbitrary
word-problem interpreter. Inputs use kg, m, s, A, V, ohm, mol, K and Hz as
appropriate. Projectile `angle` uses degrees. `gravity` is optional for potential
energy and projectile range; its default is the conventional `9.80665 m/s^2`.
Ideal gas pressure uses volume in cubic metres and `R=8.31446261815324 J/(mol*K)`.
Example outputs are `30 N`, `9 J`, approximately `40.7886485191 m` for projectile
range, and approximately `99773.5514178 Pa` for the gas example. Formulas and
assumptions accompany the results; measurement uncertainty is not propagated.

Conversions compare dimensions. Supported units: `m,mm,cm,km,in,ft,mi`,
`kg,g,mg,lb`, `s,ms,min,h,day`, `A,K,mol,rad,deg`, `N,J,kJ,W,Pa,kPa,bar,atm`,
`L,mL,Hz,V,ohm`. Compose them with `*`, `/` and integer powers; case matters.
Standalone `C,F,K` conversion handles absolute temperatures and checks absolute
zero. Temperature differences and compound Celsius/Fahrenheit units are outside
this version.

Chemical balancing uses an exact atom-conservation matrix and a unique positive
integer nullspace ratio. It verifies each element independently; the combustion
example gives `2C2H6 + 7O2 -> 4CO2 + 6H2O`. This establishes atom conservation,
not reaction feasibility. Neutral formulas support parentheses, square brackets,
Unicode subscripts, common phase suffixes and middle-dot hydrates (`CuSO4·5H2O`).
Omit input coefficients. Ionic/redox charge balancing and ambiguous mixtures are
outside this version. All 118 element symbols are recognized for balancing;
approximate molar mass has a declared 39-element table of common elements.
`Ca(OH)2` gives approximately `74.092 g/mol`.

Reference data: [CIAAW 2024 abridged atomic weights](https://www.ciaaw.org/abridged-atomic-weights.htm),
[BIPM conventional gravity example](https://jcgm.bipm.org/vim/en/2.12.html),
and the [NIST gas-constant implementation](https://pages.nist.gov/teqp-docs/en/stable/_static/doxygen/html/namespaceteqp_1_1constants.html).

## Procedural stories

```text
story
story fantasy seed=42 hero=Mira
story mystery seed=7 about a missing keeper
generate a story scifi seed=12
```

The engine samples a world, protagonist, objective and positive action costs.
Dijkstra's algorithm searches world states for a valid plan. Actions require
facts, add facts and sometimes consume them: learn a route, prepare a tool or
help an ally, travel, overcome an obstacle, find a key, resolve the objective and
return home. Each rendered scene corresponds to an action whose prerequisites
were satisfied. It checks that the final world satisfies the goal.

The same seed, options and engine version reproduce the story. Without a seed,
the engine creates one and returns it. `--json` exposes the goal and each action's
before/after facts. The genre/action/scene vocabulary is authored; plans, routes,
names and combinations vary. An `about` topic is a literal narrative hook, not
semantic understanding of any arbitrary subject. This cannot replace an LLM's
unrestricted prose or general knowledge.

## Python entry point and execution limits

```python
from services.computation import calculate

result = calculate("differentiate x^3 + sin(x) wrt x")
print(result.success, result.value)
print(result.render())
```

This synchronous function starts an owned isolated Python interpreter; async
callers use `asyncio.to_thread`. Each calculation has an eight-second deadline;
the standard-library subprocess runner kills and reaps a timed-out child. Two
concurrent calculations are allowed; further requests return busy immediately.
There is no retained worker, calculation history or additional model. Importing
the engine does not load SymPy until a math/science worker needs it. Fresh worker
startup adds latency; see the recorded local benchmark for measured numbers.

Input is limited to 1600 command characters and 512 per expression. AST nodes,
nesting, literals, numeric powers, matrix sizes and outputs are bounded. The
allowlisted AST constructs SymPy objects directly; user strings never enter
Python `eval`, `sympify` or `parse_expr`. This follows the
[SymPy parser's documented warning](https://docs.sympy.org/latest/modules/parsing.html).
These bounds and process deadlines limit work; this is not an operating-system
memory sandbox for symbolic algorithms. Use `calculate`, rather than internal
`evaluate`, when calling from an application.
