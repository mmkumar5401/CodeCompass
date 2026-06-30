# Refactoring: Localized CodeCompass Memory & Graph

## Overview

Transition CodeCompass from a global, Neo4j-backed memory system to a localized, file-based system. Each repository will maintain its own knowledge graph and memory within a `.codecompass` folder in its root directory. This transforms the tool from a "server-dependent index" into a "portable project asset," allowing the knowledge graph to live and evolve alongside the code it describes.

---

## Problem

Currently, CodeCompass acts as a global memory for all repositories, requiring a running Neo4j instance. This creates several critical frictions:
- **High Barrier to Entry**: Users cannot run the tool without setting up and maintaining a Neo4j database.
- **Lack of Portability**: The code graph is decoupled from the repository. If a repo is moved or shared, its "intelligence" (the graph) stays behind in a remote database.
- **Global Namespace Collisions**: Project names must be unique globally, leading to management overhead.
- **Heavyweight Infrastructure**: Using a full graph database for what is essentially a local project index is overkill and adds unnecessary latency and complexity.

---

## Acceptance Criteria

- [ ] **Localization Infrastructure**: Implementing `codecompass init <repo_path>` creates a `.codecompass` directory containing `graph.json`, `memory.md`, and `learnings.md`.
- [ ] **Graph Engine Migration**: All Neo4j dependencies and Cypher queries are removed and replaced with `networkx` and standard Python `json` persistence.
- [ ] **Local Ingestion**: `codecompass ingest-code` automatically detects the local `.codecompass` folder and updates `graph.json` without requiring a project name flag.
- [ ] **Query Parity**: All existing traversal features (`--impact`, `--deps`, `--tree`, etc.) are re-implemented using NetworkX and return results identical to the previous Neo4j implementation.
- [ ] **Performance Benchmark**: Loading the local `graph.json` and executing a 3-hop traversal must complete in < 500ms for projects with up to 5,000 nodes.
- [ ] **Zero-Config Startup**: The tool must be fully functional immediately after `pip install` without requiring any environment variables for a database URI or credentials.

---

## Tests

- **End-to-End Happy Path**: `init` $\to$ `ingest-code` $\to$ `query --impact "some_function"` $\to$ assert the result correctly identifies the affected files in the local `.codecompass/graph.json`.
- **Empty/New Repo**: Run `ingest-code` on a directory with no supported files $\to$ assert that `.codecompass` is initialized but `graph.json` remains empty/valid without crashing.
- **Corrupted Graph Recovery**: Manually corrupt `graph.json` $\to$ run `ingest-code` $\to$ assert the system detects the corruption and regenerates the graph from source files.
- **Cross-Project Isolation**: Ingest Repo A and Repo B $\to$ assert that queries in Repo A do not return any entities or nodes from Repo B.
- **Scale Test**: Ingest a project with 100+ files $\to$ assert that `graph.json` is written and read without memory spikes or timeouts.

---

## Notes

- **Where to start**: 
    - Add `networkx` to `requirements.txt`.
    - Create `graph/local_graph_client.py` to mirror the interface of `CodeGraphClient`.
    - Use `networkx.node_link_data` or a custom schema for `graph.json` to ensure easy serialization.
- **Dependencies**: The `ingestion/` logic (parsers, chunkers) remains mostly unchanged; only the `graph_writer.py` and `code_graph_client.py` need significant replacement.
- **Constraint**: Ensure that `.codecompass` is added to a suggested `.gitignore` or handled gracefully so users don't accidentally commit massive JSON graphs if they don't want to.
- **Key Files to Modify**: `main.py` (CLI), `graph/code_graph_client.py` (Client), `graph/code_query_cli.py` (Queries), `ingestion/graph_writer.py` (Persistence).
