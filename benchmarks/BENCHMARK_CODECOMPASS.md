# CodeCompass benchmark — token cost using the graph

Run this on **any** repository to measure how many tokens it takes to complete a
standard set of navigation/change tasks **using CodeCompass** (`grep`,
`impact`, `blast_radius`, `deps`, `flow`, `dead_code`) plus targeted reads.

Pair it with `BENCHMARK_BASELINE.md` (same tasks, grep/read only) to compare.
Both files use the **same six tasks** so the numbers line up task-for-task.

## Setup

1. Pick the target repo. Note its primary source directory (e.g. `lib/`, `src/`).
2. Ingest it: `codecompass ingest-code <repo>` (or `mcp: ingest`).
3. For each task below, **log every tool call and its response size**, in bytes,
   and estimate tokens as `bytes / 4`. Keep a per-task running total.
4. "Reach a verified answer" means: don't stop at the raw tool output — read the
   specific slice needed to confirm it (Read tool / `sed -n`), and count those
   reads too. A cheap-but-wrong answer does not count as done.

> Report the exact symbols/files you chose for this repo — targets are
> repo-specific, the task *shapes* are fixed.

## The six tasks

### T1 — Impact (who calls X, disambiguated)
Choose a method name that exists on more than one receiver/class if the repo has
one (a collision); otherwise any widely-called function.
- Run `impact("<Receiver.method>")` (receiver-qualified when there's a collision).
- Verify: read each returned caller's slice to confirm it's a real caller.
- Record: tokens for the `impact` call + verify reads.

### T2 — Blast radius / transitive dependents
Pick a core source file.
- Run `blast_radius("<path>")`.
- Verify the direct dependents; note any transitive dependents the tool misses
  (walk one `deps`/`impact` hop out to check) and any false edges you rule out.
- Record: tokens to a *correct* dependent set.

### T3 — Dead code audit
- Run `dead_code()`.
- Spot-check a sample of candidates against source (read their slice) to classify
  real-dead vs public-API/entry-point/dynamic-dispatch false positives.
- Record: tokens for the call + verification of the sample.

### T4 — Flow trace
Pick an entry point (a request handler, a CLI command, a pipeline entry).
- Run lean `flow("<entry>")` to get the call structure.
- If a human-readable walkthrough is the goal, also run `flow_summary(...)`
  (record it separately — it's heavier).
- Record: tokens for `flow` (and `flow_summary` if used).

### T5 — Find-and-edit (anchored change)
A small change at a known-ish anchor (e.g. "add a header next to the existing
`X-*` header", "add a field next to an existing config default").
- Discover the location: `grep("<anchor keyword>")` → then
  `flow`/`impact` to confirm the exact function.
- Read the specific slice, make the edit.
- Record: tokens to pinpoint the edit site (the FIND phase), separate from apply.

### T6 — Vague feature scoping (orientation)
A product request with **no symbol given** (e.g. "add response caching",
"add rate limiting", "add request logging").
- Orient: `tree` (read the layout in slices to find where it belongs), then
  `flow`/`impact` on the candidate entry/exit points.
- Produce a concrete plan: the files + functions + insertion points.
- Record: tokens to reach the concrete plan.

## Output — write `RESULTS_CODECOMPASS.md`

| Task | Target chosen | Tool calls | Tokens | Correct? |
|------|---------------|-----------|-------:|----------|
| T1 Impact | | | | |
| T2 Blast radius | | | | |
| T3 Dead code | | | | |
| T4 Flow | | | | |
| T5 Find-and-edit (FIND) | | | | |
| T6 Vague feature | | | | |
| **Total** | | | | |

Also record: repo name, commit, primary source dir, and any tool that returned a
wrong/incomplete answer (with what verification caught it). Then compare against
`RESULTS_BASELINE.md` task-for-task.
