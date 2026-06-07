# Ingest Agent

Use this when adding new knowledge to the graph — a codebase, document, URL,
or manually discovered fact.

---

## Operations

### Ingest a codebase (code graph)

```bash
# Full ingest with Haiku normalization (costs API credits)
python main.py ingest-code /path/to/repo --project <name>

# Skip normalization (free, less clean entity names)
python main.py ingest-code /path/to/repo --project <name> --skip-normalize

# Native normalization (Claude Code does it, no API credits)
python main.py ingest-code /path/to/repo --project <name> --dump-triples /tmp/raw.json
# → read /tmp/raw.json, normalize, write /tmp/normalized.json
python main.py load-triples /tmp/normalized.json --project <name>
python main.py resolve
```

After ingesting, verify:
```bash
python -m graph.code_query_cli --tree <name>
```

---

### Ingest a document or URL (concept graph)

```bash
# From a URL (arxiv abstract pages auto-redirect to PDF)
python graph/ingest_cli.py --url "https://arxiv.org/abs/2105.00188"

# From a local file
python graph/ingest_cli.py --file path/to/paper.pdf
python graph/ingest_cli.py --file path/to/notes.txt

# Zero cost: read the file yourself, extract, write
# 1. Read the file
# 2. Extract entities and relationships
# 3. Write them:
python graph/remember_batch_cli.py '[
  {"from": "Entity A", "relation": "DEPENDS_ON", "to": "Entity B"}
]'
```

---

### Save a single discovered fact

```bash
python graph/remember_cli.py "Entity A" "RELATION_TYPE" "Entity B"
```

Use during any session when you discover a relationship not yet in the graph.

---

### Save multiple facts at once

```bash
python graph/remember_batch_cli.py '[
  {"from": "seed_finder", "relation": "USES", "to": "Neo4j get_all_node_names"},
  {"from": "navigator_agent", "relation": "IMPLEMENTS", "to": "branch-aware BFS"}
]'
```

---

### Clean up duplicate entities

```bash
python main.py resolve           # merge duplicate nodes
python main.py resolve --dry-run # preview first
```

Run this after any bulk ingest. Entities like "BKT" and "Bayesian Knowledge
Tracing" get merged into one canonical node.

---

### Keep code graph fresh while editing

Run the file watcher in a separate terminal while working on a project:

```bash
python -c "
from graph import db_router
from ingestion.hierarchy_builder import build_hierarchy
from ingestion.file_watcher import FileWatcher

project = '<project>'
root = '/path/to/repo'
client = db_router.project_client(project)
file_id_map = build_hierarchy(root, project, client)
watcher = FileWatcher(root, project, client, file_id_map)
watcher.start()
"
```

---

## Extraction rules (for manual/native ingest)

- **Entities**: concrete nouns — concepts, systems, components, algorithms, people
- **Relations**: ALL_CAPS_UNDERSCORES — CAUSES, DEPENDS_ON, HAS_COMPONENT, EXTENDS, IS_A, USED_BY, IMPLEMENTS, GOVERNS
- Only extract **clear, explicit** relationships — not vague associations
- Use **consistent names** — same concept always gets the same name
- After writing, verify: `python graph/query_cli.py --seeds "Entity A,Entity B"`
