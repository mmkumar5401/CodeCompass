# Hybrid Agent

Use this when the task links a concept (from docs/architecture) to its
implementation (in code), or vice versa.

This is the most powerful mode — the doc graph knows WHAT something is,
the code graph knows WHERE it lives.

---

## Operations

### "How is concept X implemented in code?"

```
Concept → Implementation
```

```bash
# Step 1: find the concept and its relationships in the doc graph
python graph/query_cli.py "X" --hops 2

# Step 2: extract entity names from the result
# Step 3: find those entities in the code graph
python -m graph.code_query_cli --impact <entity_from_step1> --project <project> --plain
# or
python -m graph.code_query_cli --deps <file_that_implements_it> --project <project> --plain
```

**Example:**
```bash
# "How is seed finding implemented?"
python graph/query_cli.py "seed finding"
# → seed_finder USES Neo4j get_all_node_names, seed_finder FEEDS_INTO navigator_agent

python -m graph.code_query_cli --impact seed_finder --project graphrag --plain
# → seed_finder is defined in query/seed_finder.py, called by query/agentic_agent.py

# Now read query/seed_finder.py for the actual implementation
```

---

### "What concept/paper describes what this code does?"

```
Implementation → Concept
```

```bash
# Step 1: find what the file depends on
python -m graph.code_query_cli --deps <file> --project <project> --plain

# Step 2: search the concept graph for the module/function names found
python graph/query_cli.py "<module_or_function_name>" --hops 2
```

**Example:**
```bash
# "What is the theory behind relevance_filter?"
python -m graph.code_query_cli --deps query/relevance_filter.py --project graphrag --plain
# → imports: models.types, anthropic, neo4j

python graph/query_cli.py "relevance filter BFS scoring" --hops 2
# → relevance_filter RETURNS FilterResult
#   RELEVANCE_THRESHOLD GOVERNS relevance_filter
#   navigator_agent CALLS_PER_LAYER relevance_filter
```

---

### "Add a feature described in a doc to the codebase"

```bash
# Step 1: find the concept in the doc graph
python graph/query_cli.py "<feature name>" --hops 2

# Step 2: find where related code lives
python -m graph.code_query_cli --impact <related_entity> --project <project> --plain

# Step 3: read the identified files
# Step 4: implement — following patterns from the existing code
# Step 5: after implementing, save the new link to the graph
python graph/remember_batch_cli.py '[
  {"from": "<new_function>", "relation": "IMPLEMENTS", "to": "<concept_from_doc>"}
]'
```

---

### "Does the code match the documented design?"

```bash
# Step 1: get the documented design from the concept graph
python graph/query_cli.py "<component>" --hops 3

# Step 2: get the actual implementation structure
python -m graph.code_query_cli --deps <file> --project <project> --plain
python -m graph.code_query_cli --trace <entry_point> --project <project> --plain

# Step 3: compare edges — flag any discrepancy between documented and actual
# Step 4: if the code diverged from the design, update the graph
python graph/remember_batch_cli.py '[{"from": "...", "relation": "...", "to": "..."}]'
```

---

## Linking new code to existing concepts

Whenever you implement something that corresponds to an existing concept node,
create the link explicitly:

```bash
python graph/remember_batch_cli.py '[
  {"from": "build_hierarchy", "relation": "IS_PART_OF", "to": "ingestion pipeline"},
  {"from": "FileWatcher", "relation": "IMPLEMENTS", "to": "incremental graph updates"}
]'
```

This is how the graph becomes a living map — code and docs stay connected
as the project evolves.

---

## Rules

- Always query the doc graph first for conceptual tasks — it knows the intent
- Always query the code graph for structural tasks — it knows the reality
- When both graphs return results, synthesize: docs = why, code = how
- After any hybrid operation, commit the cross-links you discovered
