# Local computation and procedural story engine

The owner requested a mathematical engine for FRIDAY, including vector algebra,
calculus, chemistry, physics and stories generated without an LLM.

Acceptance: exact arithmetic and symbolic algebra/calculus; bounded vector and
matrix operations; descriptive statistics; dimension-checked unit conversions;
named SI physics formulas; atom-conserving equation balancing and approximate
molar masses; seeded stories planned from goals, prerequisites and world-state
changes. Results expose working, assumptions and unsupported cases. No generated
explanation may claim a calculation succeeded when it remains unevaluated.

Use the installed SymPy 1.14 dependency, declare it explicitly, and use the Python
standard library elsewhere. Build expressions from an AST allowlist, never eval,
sympify(string) or parse_expr. Restrict input size/depth, powers, dimensions and
formula size. Run computations in owned subprocesses with a hard timeout and a
small concurrency cap. Keep worker startup hidden on Windows. No persistent
worker, downloaded model, network request or owner-data write is necessary.

Shared command dispatch must preserve formula case and punctuation, precede
multi-command/typing interpretation, and retain existing confirmation handling.
Chat and voice must bypass search/screen interpretation and LLM reply polishing
for engine commands. Telegram, Island and Control Center inherit shared chat
routing. Add a standalone CLI and a reproducible demonstration.

Stories use a finite authored world/action vocabulary and generated action plans;
this is procedural storytelling, not unrestricted language understanding. Exact
math is distinct from approximate measurements and idealized physics models.

Policy decision receipt: allow user-requested reversible local source, dependency
declaration, test and documentation edits. Root is the sole writer;
engine_integration_research and science_engine_research are read-only researchers.
Local policy is legacy; no tracked collaboration/action-capability adapter exists.
Ruflo guidance/memory tools are unregistered; offline CLI discovery found no cached
package. Existing architecture, local policy and preceding implementation receipts
were inspected. No install, backend restart, external message, commit, publish or
release is included. Test storage is isolated by the existing fixtures. Final
source hashes, benchmark and execution evidence belong in tasks/computation-engine.
