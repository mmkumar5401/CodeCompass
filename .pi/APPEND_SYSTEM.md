# CodeCompass-first navigation

You may not use `cat`, `grep`, or `rg` to search or read code content.
Navigation and discovery of code structure/relationships must go through `codecompass`:

- Read `.codecompass/overview.md`, `.codecompass/memory.md`, and `.codecompass/learnings.md` at the start of every session.
- Use `codecompass query --tree` for project structure.
- Use `codecompass query --blast-radius <file_or_symbol>` before editing anything.
- Use `codecompass query --impact <symbol>` before calling or importing any symbol.
- Use `codecompass query --flow <entry_symbol> --format json` to trace behavior end-to-end.
- Use `codecompass query --deps <file>` to see what a file depends on.
- Use `codecompass query --dead-code` to find unused entities.
- Run `codecompass ingest-code` after creating, deleting, or renaming files.

Open files with `read` only after codecompass tells you which files matter.

## Graph vs. `ls`/`find` — how to decide

Use codecompass when the question is about code structure or relationships:
"what calls this", "what depends on this file", "what does this module do",
"how does this flow work", "is this dead code". The graph knows the real
dependency edges; a directory listing does not.

Use `ls`/`find` when the question has nothing to do with code relationships:
confirming a generated/output file exists, listing a build/dist/log
directory, checking test fixtures or assets, or any path the graph doesn't
index. These are fine — don't force codecompass onto questions it can't
answer.
