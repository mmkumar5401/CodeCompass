# Design Decisions

## Always use --plain with code_query_cli

Rich table output (default) uses box-drawing characters and inflates context ~60%.
Plain output: ~1,069 chars. Rich output: ~2,841 chars for the same data.
**Rule: every code_query_cli call must end with --plain.**

## --deps before --impact

`--deps path/to/file.py` always returns useful import/dependency info.
`--impact FunctionName` returns "Nothing calls X" for functions not called externally — misleading.
**Rule: default to --deps. Add --impact only when checking for callers before renaming/removing.**

## Save graph facts only when asked

Do not write to the graph after every response. Only write when the user explicitly asks
or at session end via the auto_memory hook.

## Two-graph separation

Doc graph and code graph are separate Neo4j databases routed by `graph/db_router.py`.
Cross-links (doc concept ↔ code entity) are written manually via `remember_batch_cli.py`
using relations like IMPLEMENTS, APPLIES, IS_DESCRIBED_BY.

## Native ingestion (zero API cost)

For code: `python main.py ingest-code /path/to/repo --project <name> --skip-normalize`
For docs: read the file yourself, extract triples, write via `remember_batch_cli.py`
API-powered mode (Haiku) only needed for large documents where manual extraction is impractical.
