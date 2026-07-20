# CodeCompass benchmark results — JS · Python · PHP

Token cost to complete six standard navigation/change tasks on real repositories,
**CodeCompass vs. traditional grep/read** (no graph). Measured as *tokens to a
verified answer*: the tool/query output **plus** the code the agent still has to
read to trust and act on it (bytes ÷ 4). Both sides log their own byte accounting;
grep/read baselines are real cold-session runs.

## Headline

| Language | Repo | CodeCompass | grep/read baseline | Reduction |
|---|---|---:|---:|---:|
| Python | `psf/requests` | **1,290** | 3,875 | **−67%** |
| Python | `pallets/click` | **1,669** | 9,338 | **−82%** |
| PHP | `guzzlehttp/guzzle` | **1,707** | 4,985 | **−66%** |
| JavaScript | `expressjs/express` | **1,526** | ~8,575 † | **−82%** † |

† The express baseline is from an earlier real cold-session run over a comparable
task set; the CodeCompass figure uses the final tooling. Python/PHP baselines are
full six-task cold-session runs against the identical repo.

**Across all four languages CodeCompass wins by 66–82%**, and by task type the
pattern is consistent: it wins the *relational* and *discovery* tasks decisively,
ties grep on purely textual finds, and its edge grows on codebases with name
collisions.

## Per-task breakdown (tokens)

| Task | requests (Py) | click (Py) | guzzle (PHP) | express (JS) |
|---|---:|---:|---:|---:|
| T1 Impact (who calls X, disambiguated) | 91 | 163 | 2* | 103 |
| T2 Blast radius (what depends on file) | 184 | 280 | 408 | 111 |
| T3 Dead code (scoped) | 3 | 112 | 27 | 162 |
| T4 Flow trace (hops=1 path) | 726 | 291 | 436 | 500 |
| T5 Find (graph `grep`) | 88 | 209 | 226 | 44 |
| T6 Vague feature (`grep` the concept) | 198 | 614 | 608 | 606 |
| **Total** | **1,290** | **1,669** | **1,707** | **1,526** |

\* `Client::send` is public API — invoked by external consumers, so it correctly
has ~0 in-repo callers. Not an empty measurement error; the graph confirms it
instantly where grep must scan to prove the negative.

## What makes the difference

- **Impact wins biggest.** Node de-merge means `impact` returns only the precise
  callers of a *specific* method — no test noise, no same-named look-alikes — and
  each row carries the real call-site `file:line`, so verification reads a
  ~6-line slice instead of a whole function. On click's `Command.invoke` (which
  collides with `Context.invoke` and `Group.invoke` in the same file) the baseline
  spent 1,426 tokens disambiguating by reading regions; CodeCompass answered
  correctly for a fraction.
- **Discovery is a first-class step.** For a vague feature request that names a
  concept ("session timeout"), `grep`-ing the graph for that concept scopes
  straight to it — far cheaper than dumping the whole index or reading files.
- **Flow is lean.** `flow` returns call structure only (no embedded source);
  following one path at `hops=1` beats pulling a whole fan-out.
- **Grep wins the textual ties.** Anchored finds of a unique string (T5) are
  grep's home turf; CodeCompass matches it via graph `grep`, and the guardrail
  keeps that ergonomics pointed at the graph.

## Language parity

All three parser-level features work across every call-based language:

| Feature | JS/TS | Python | PHP |
|---|:---:|:---:|:---:|
| Receiver capture | ✅ | ✅ | ✅ |
| Type inference (`new`/annotation/`self`) | ✅ | ✅ | ✅ |
| Return-type inference | ✅ | ✅ | ✅ |
| Export / public-API awareness | ✅ | ✅ | ✅ (real `public`/`private`) |
| Node de-merge (file **and** class) | ✅ | ✅ | ✅ |

Graph-level features — de-merge, `grep`, the `resolved` flag,
lean `flow` — are language-agnostic and cover HTML/CSS as well (selectors and
elements de-merge by file; no receiver/type/export concept applies).

## Honest limitations

- **Public-API entry points** (`Client::send`) have no in-repo callers by design —
  cheap for both approaches, not a CodeCompass win.
- **Dynamic dispatch** (`super().invoke()`, `adapter->send()` on an untyped
  variable) can't be resolved statically. Those calls are surfaced flagged
  `resolved: false` — never dropped, never claimed as precise. Return-type
  inference recovers the annotated cases; the rest need whole-program data-flow.
- **Small, well-named repos** narrow the gap: on a tiny module where every symbol
  is obvious, grep is very efficient. The advantage grows with codebase size and
  name collisions.

## Method

Six tasks per repo, same targets on both sides. CodeCompass numbers are measured
from live ingests with the final parser (file+class-qualified de-merge, receiver/
return-type resolution). Baselines are real grep/find/cat/sed/Read cold sessions.
Dead-code is scoped to the target file on both sides for comparability. 1 token ≈
4 bytes throughout.
