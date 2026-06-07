# Concept Agent

Use this when the task involves understanding architecture, algorithms, design
decisions, or relationships between ideas — not specific file edits.

---

## Operations

### Understand a concept

```bash
python graph/query_cli.py "your question here" --hops 2
```

Returns a subgraph of related concepts and their relationships.
Reason over the edges — do not hallucinate facts not present in the graph.

**Example:**
```bash
python graph/query_cli.py "how does seed finding work in the query pipeline?"
# → returns: seed_finder FEEDS_INTO navigator_agent
#             seed_finder USES Claude Haiku
#             seed_finder USES Neo4j get_all_node_names
```

---

### Deep concept traversal

```bash
python graph/query_cli.py "question" --hops 3
```

Use when the concept has many indirect relationships (e.g., understanding a
full pipeline end-to-end rather than one component).

---

### Query from known seed nodes

```bash
python graph/query_cli.py --seeds "seed_finder,navigator_agent,answer_agent"
```

Use when you already know which concept nodes are relevant — faster than
keyword search and avoids false seed matches.

---

### See all available concepts

```bash
python graph/query_cli.py --list-nodes
```

Use when you're not sure what's in the graph, or to verify a concept name
before using it as a seed.

---

### Save a new concept or relationship

After answering a question, if you discovered a relationship NOT already in
the graph, commit it:

```bash
python graph/remember_batch_cli.py '[
  {"from": "entity_resolver", "relation": "USES", "to": "Claude Haiku"},
  {"from": "entity_resolver", "relation": "READS_FROM", "to": "Neo4j"}
]'
```

**Rules for writing facts:**
- Only commit facts directly supported by what you read — not inference
- Use ALL_CAPS_UNDERSCORES for relation types
- Use consistent entity names — same concept = same name every time
- Do not duplicate facts already in the graph

---

## Rules

- If the graph returns nothing, say so — do not answer from training knowledge alone
- After every answer, check if new relationships were discovered and commit them
- Concept queries are zero API cost — run them freely before answering
