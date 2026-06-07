# GraphRAG Agent Routing Guide

Before making any edit, answering any question, or creating anything new —
run `python graph/nav_agent.py "<your task>"` first.

The nav_agent handles routing automatically, but this guide explains the
decision logic and when to override it manually.

---

## Decision tree

```
What kind of task is this?
│
├── "How does X work?" / "What is X?" / "Explain X"
│   └── → CONCEPT agent  (doc graph, query_cli)
│
├── "Edit / add / modify / fix code in X"
│   └── → CODE agent  (code graph, code_query_cli --deps)
│
├── "What calls X?" / "What breaks if I change X?"
│   └── → IMPACT agent  (code graph, code_query_cli --impact)
│
├── "How is concept X implemented in code?"
│   └── → HYBRID agent  (doc graph first → code graph second)
│
└── "Ingest / remember / save X"
    └── → INGEST agent  (remember_batch_cli or ingest_cli)
```

---

## Quick reference

| Task type | Primary tool | Secondary tool |
|---|---|---|
| Understand a concept | `query_cli.py` | — |
| Edit a file | `code_query_cli --deps <file>` | `query_cli.py` |
| Find callers / impact | `code_query_cli --impact <entity>` | — |
| Concept → implementation | `query_cli.py` → `code_query_cli --deps` | — |
| Implementation → concept | `code_query_cli --deps` → `query_cli.py` | — |
| Browse project structure | `code_query_cli --tree <project>` | — |
| Trace a call chain | `code_query_cli --trace <entity>` | — |
| Save a new fact | `remember_batch_cli.py` | — |
| Ingest a document/URL | `ingest_cli.py` | — |

---

## When graph returns nothing

If `nav_agent.py` returns no graph context:
1. Check `python graph/query_cli.py --list-nodes` — is the doc graph empty?
2. Check `python -m graph.code_query_cli --tree graphrag` — is the code graph empty?
3. If both are empty → ingest first: see `agents/INGEST.md`
4. If only doc graph is empty → the question is code-structural, use CODE agent directly
5. If only code graph is empty → ingest the codebase: `python main.py ingest-code /path/to/repo --project <name>`
