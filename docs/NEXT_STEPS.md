# GraphRAG — Next Steps: React Graph Explorer UI

## What we're building

A React app where you type a component name, hit search, and get back:
- The matching node (function / class / module / file)
- All its connections rendered as an interactive graph
- Clickable nodes — click any neighbour to re-centre the graph on it
- A sidebar showing the raw edges (relation type, source file, line number)

---

## Architecture

```
Browser (React)
    ↕  REST / WebSocket
FastAPI (Python)          ← sits in front of Neo4j, reuses all existing graph logic
    ↕
Neo4j (existing)
```

One new piece: a thin **FastAPI server** that exposes the Neo4j graph over HTTP.
The React app never touches Neo4j directly.

---

## Phase 1 — FastAPI backend (1 day)

New file: `api/server.py`

### Endpoints needed

| Method | Path | What it does |
|---|---|---|
| `GET /search?q=AuthService&project=frontend` | Fuzzy-match entity names, return top 10 hits |
| `GET /node/{id}/neighbours?hops=1&project=frontend` | Return all neighbours up to N hops |
| `GET /node/{id}/impact?project=frontend` | Reverse CALLS traversal |
| `GET /node/{id}/deps?project=frontend` | Forward IMPORTS traversal |
| `GET /projects` | List all ingested projects |
| `GET /project/{name}/tree` | Full folder/file hierarchy |

### Response shape (all endpoints)

```json
{
  "nodes": [
    { "id": "uuid", "name": "AuthService", "type": "class", "file": "src/auth/auth.service.ts", "project": "frontend" }
  ],
  "edges": [
    { "from": "uuid-a", "to": "uuid-b", "type": "IMPORTS", "file": "src/auth/auth.service.ts", "line": 3 }
  ]
}
```

Same shape for every endpoint — the React app renders whatever comes back.

### Stack
```bash
pip install fastapi uvicorn
```

```bash
# Run
uvicorn api.server:app --reload --port 8000
```

---

## Phase 2 — React app (2 days)

### Tech choices

| Concern | Library | Why |
|---|---|---|
| Graph rendering | **React Flow** | Best DX, handles large graphs, built-in minimap + zoom |
| Search input | React (no lib) | Simple controlled input + debounce |
| Sidebar / panels | **shadcn/ui** | Unstyled, composable, works with Tailwind |
| Data fetching | **TanStack Query** | Caching + loading states for free |
| Routing | **React Router** | `/explore/:project/:nodeId` — shareable URLs |
| Styling | **Tailwind CSS** | Already familiar pattern |

### Scaffold

```bash
npm create vite@latest graphrag-ui -- --template react-ts
cd graphrag-ui
npm install @xyflow/react @tanstack/react-query react-router-dom
npm install -D tailwindcss
npx shadcn@latest init
```

---

## Phase 3 — UI layout

```
┌─────────────────────────────────────────────────────────────┐
│  🔍  [AuthService          ] [frontend ▼]  [1 hop ▼]  [Search] │  ← top bar
├───────────────────────────┬─────────────────────────────────┤
│                           │  Selected: AuthService           │
│                           │  Type: class                     │
│   React Flow canvas       │  File: src/auth/auth.service.ts  │
│                           │  Project: frontend               │
│   [AuthService]──IMPORTS──▶[HttpClient]                      │  ← sidebar
│       │                   │                                  │
│   CALLS                   │  Connections (8)                 │
│       ▼                   │  ──────────────────────────────  │
│   [login()]               │  IMPORTS → HttpClient  :3        │
│                           │  IMPORTS → Router      :7        │
│                           │  CALLS   → login()     :42       │
│                           │  DEFINED_IN → auth.service :1    │
└───────────────────────────┴─────────────────────────────────┘
```

### Node colour coding (matches the PDF)

| Entity type | Colour |
|---|---|
| `function` | Blue |
| `class` | Purple |
| `module` | Green |
| `file` | Teal |
| `css_selector` | Orange |
| `html_element` | Yellow |

### Edge label coding

| Relation | Line style |
|---|---|
| `CALLS` | Solid red |
| `IMPORTS` | Solid blue |
| `INHERITS` | Dashed purple |
| `DEFINED_IN` | Dotted gray |
| `STYLES` | Solid orange |
| `CONTAINS` | Dotted teal |

---

## Phase 4 — Search behaviour

1. User types `"AuthSer"` → debounced 300ms → `GET /search?q=AuthSer&project=frontend`
2. Dropdown shows top 10 matches with type badge
3. User clicks a result → `GET /node/{id}/neighbours?hops=1`
4. React Flow renders the subgraph
5. User clicks any node in the canvas → fetch that node's neighbours, expand in place
6. Breadcrumb trail at top shows navigation path (`AuthService → HttpClient → ...`)

---

## Phase 5 — Nice to have (later)

- **Path finder** — enter two nodes, find shortest path between them (Cypher `shortestPath`)
- **Impact highlight** — red-highlight all nodes that would break if selected node changes
- **Filter by relation type** — toggle CALLS / IMPORTS / INHERITS on/off
- **Export subgraph** — download the visible graph as JSON or PNG
- **Live update indicator** — WebSocket ping from `file_watcher.py` → flash affected nodes green when the graph updates

---

## File structure

```
graphrag/
├── api/
│   ├── __init__.py
│   ├── server.py        ← FastAPI app
│   ├── routes/
│   │   ├── search.py
│   │   ├── nodes.py
│   │   └── projects.py
│   └── schemas.py       ← Pydantic response models
└── ui/
    ├── package.json
    ├── src/
    │   ├── App.tsx
    │   ├── components/
    │   │   ├── SearchBar.tsx
    │   │   ├── GraphCanvas.tsx   ← React Flow wrapper
    │   │   ├── NodeSidebar.tsx
    │   │   └── ProjectPicker.tsx
    │   ├── hooks/
    │   │   ├── useSearch.ts
    │   │   └── useNodeGraph.ts
    │   └── lib/
    │       ├── api.ts            ← typed fetch wrappers
    │       └── graphLayout.ts    ← dagre auto-layout for React Flow
    └── vite.config.ts
```

---

## Start here

```bash
# 1. Backend first — verify API works before touching React
pip install fastapi uvicorn
# build api/server.py
uvicorn api.server:app --reload

# 2. Test with curl
curl "http://localhost:8000/search?q=AuthService&project=frontend"

# 3. Scaffold React
cd graphrag
npm create vite@latest ui -- --template react-ts
```

Say the word and we start with the FastAPI server.
