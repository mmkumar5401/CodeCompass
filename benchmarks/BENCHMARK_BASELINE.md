# Baseline benchmark — token cost using grep/read only

Run this on **any** repository to measure how many tokens it takes to complete a
standard set of navigation/change tasks **the traditional way** — `grep`/`rg`,
`find`, `cat`/`sed`/Read — with **no CodeCompass**.

Pair it with `BENCHMARK_CODECOMPASS.md` (same tasks, graph tools). Both files use
the **same six tasks** so the numbers line up task-for-task. Use the **same
target symbols/files** the CodeCompass run chose, so it's apples-to-apples.

## Setup

1. Use a plain clone of the target repo — no CodeCompass, no `.claude/` hooks.
2. Work naturally with `ls`/`find`/`grep`/`rg`/`cat`/`sed`/Read. You may use
   general knowledge of the framework, but every *specific* claim (which
   function, which file/line) must be grounded in source you actually read here.
3. For each task, **log every command and file (or slice) read**, byte size via
   `wc -c` on the output actually produced/read, and estimate tokens as
   `bytes / 4`. Keep a per-task running total.
4. "Reach a verified answer" = confirm the answer from source, not the first
   plausible match. **Dead ends count** — files you open that turn out
   irrelevant are part of the cost of navigating without a map.

## The six tasks

(Use the same targets as the CodeCompass run for a fair comparison.)

### T1 — Impact (who calls X, disambiguated)
Find every in-repo caller of the chosen method — and only that one if the name
collides with a same-named method on another class/receiver. `grep` the name,
then read the matching regions to classify real callers vs same-name look-alikes.
- Record: scan output bytes + bytes read to disambiguate.

### T2 — Blast radius / transitive dependents
Find every file that depends on the chosen source file, directly **or
transitively**. Grep the import/require statements, then follow the chain by
reading imports. Rule out files that are *imported by* a dependent but don't
themselves depend on the target.
- Record: tokens to a *correct* dependent set.

### T3 — Dead code audit
Enumerate definitions (grep for `def`/`function`/etc.), then reference-count each
candidate (grep its name repo-wide), excluding public API, entry points, and
dunders. This is the dominant-cost task by hand — that's expected.
- Record: bytes for the def list + the reference-count passes.

### T4 — Flow trace
Trace the call chain forward from the chosen entry point a few levels deep by
reading the entry function and following each call it makes. If a written
narration is required, count the narration text bytes too.
- Record: bytes read (+ narration if written).

### T5 — Find-and-edit (anchored change)
Locate the change site by grepping the anchor keyword, confirm it's the right
place (read the region), then make the edit.
- Record: bytes to pinpoint the edit site (the FIND phase), separate from apply.

### T6 — Vague feature scoping (orientation)
A product request with **no symbol given**. Orient by `ls`-ing the structure and
reading the entry/core files to understand where the feature belongs, then
produce a concrete plan (files + functions + insertion points).
- Record: bytes read to reach the concrete plan (include dead-end reads).

## Output — write `RESULTS_BASELINE.md`

| Task | Target used | Commands / files | Tokens | Correct? |
|------|-------------|------------------|-------:|----------|
| T1 Impact | | | | |
| T2 Blast radius | | | | |
| T3 Dead code | | | | |
| T4 Flow | | | | |
| T5 Find-and-edit (FIND) | | | | |
| T6 Vague feature | | | | |
| **Total** | | | | |

Also record: repo name, commit, primary source dir, and any dead ends (files
opened that didn't belong, with byte cost). Then compare against
`RESULTS_CODECOMPASS.md` task-for-task.
