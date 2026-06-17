# Session Learnings

Personal notes that accumulate across sessions. Copy this file to `learnings.md` after cloning:

```bash
cp memory/learnings.example.md memory/learnings.md
```

`memory/learnings.md` is gitignored — your notes stay local.

---

## How to use

Add a dated section after each meaningful session. opencode's session memory plugin auto-saves learnings on compaction. Or write directly.

Format:

```markdown
## YYYY-MM-DD: <short title>
- <specific learning — design decision, bug found, constraint discovered>
- <keep to 4–8 bullets, skip routine edits>
```

The session memory plugin also saves learnings before context is compacted.

---

## Example entries

## 2026-01-15: First ingest of my-repo
- Ingested 312 files under project `my-repo` — took ~8s with no normalization pass
- `--impact "MyClass"` returned 14 callers across 6 files — useful before refactoring
- Watcher PID file lives at `/tmp/codecompass_watcher_my-repo.pid`

## 2026-01-16: Normalization pass findings
- `--normalize` on 312 files took ~4 min and cost ~$0.02 in Haiku credits
- Merged 38 duplicate entity names (e.g. `getUserById` / `get_user_by_id`)
- Worth doing once for a large repo, not on every re-ingest
