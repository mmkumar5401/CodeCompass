"""Incremental file watcher — keeps the code graph fresh without full re-ingestion.

Uses the Observer pattern via watchdog. File system events fire callbacks
that trigger targeted re-ingestion of only the changed file. The watcher
is decoupled from the ingestion logic — it only knows how to detect changes
and hand off file paths.

Usage:
    watcher = FileWatcher(project_root, project_name, client, master_client)
    watcher.start()
    # ... runs until KeyboardInterrupt or watcher.stop()
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from graph.code_graph_client import CodeGraphClient
from ingestion.code_parser import parse_file, SUPPORTED_EXTENSIONS
from ingestion.bridge_detector import detect_bridges


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------

class _CodeFileEventHandler(FileSystemEventHandler):
    """Handles FS events for source files and triggers incremental re-ingestion."""

    def __init__(
        self,
        project_root: str,
        project_name: str,
        client: CodeGraphClient,
        file_id_map: dict[str, str],
        master_client: Optional[CodeGraphClient] = None,
    ) -> None:
        super().__init__()
        self._project_root = project_root
        self._project_name = project_name
        self._client = client
        self._file_id_map = file_id_map          # {rel_path: neo4j_file_node_id}
        self._master_client = master_client

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle_change(event.src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle_change(event.src_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        rel_path = os.path.relpath(event.src_path, self._project_root)
        self._remove_file_from_graph(rel_path)

    # ------------------------------------------------------------------
    # Core delta logic
    # ------------------------------------------------------------------

    def _handle_change(self, abs_path: str) -> None:
        """Re-parse a changed file and apply only the delta to Neo4j."""
        ext = Path(abs_path).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return

        rel_path = os.path.relpath(abs_path, self._project_root)
        print(f"[file_watcher] changed: {rel_path}")

        # 1. Delete all entity nodes sourced from this file
        self._client.delete_file_triples(rel_path, self._project_name)

        # 2. Re-parse the file into fresh triples
        new_triples = parse_file(abs_path, self._project_root)
        if not new_triples:
            return

        # 3. Write the new triples
        file_node_id = self._file_id_map.get(rel_path, "")
        for triple in new_triples:
            self._client.write_code_triple(triple, file_node_id, self._project_name)

        print(f"[file_watcher] wrote {len(new_triples)} triples for {rel_path}")

        # 4. Re-run bridge detection for the affected project if master is available
        if self._master_client:
            self._recheck_bridges()

    def _remove_file_from_graph(self, rel_path: str) -> None:
        """Purge all entity nodes for a deleted file."""
        print(f"[file_watcher] deleted: {rel_path}")
        self._client.delete_file_triples(rel_path, self._project_name)

    def _recheck_bridges(self) -> None:
        """Placeholder — full cross-project bridge re-detection on file change.

        In production this would diff only the entities that changed, but
        for correctness the simplest safe approach is a full re-run after
        any significant change. Debounce in the caller if this is too slow.
        """
        # Bridge detection requires a second client — skip if not configured
        pass


# ---------------------------------------------------------------------------
# Public watcher class
# ---------------------------------------------------------------------------

class FileWatcher:
    """Watches a project root and keeps its code graph incrementally updated."""

    def __init__(
        self,
        project_root: str,
        project_name: str,
        client: CodeGraphClient,
        file_id_map: dict[str, str],
        master_client: Optional[CodeGraphClient] = None,
    ) -> None:
        self._project_root = project_root
        self._handler = _CodeFileEventHandler(
            project_root=project_root,
            project_name=project_name,
            client=client,
            file_id_map=file_id_map,
            master_client=master_client,
        )
        self._observer = Observer()
        self._observer.schedule(self._handler, project_root, recursive=True)

    def start(self) -> None:
        """Start watching. Blocks until stop() is called or KeyboardInterrupt."""
        self._observer.start()
        print(f"[file_watcher] watching {self._project_root} — Ctrl-C to stop")
        try:
            while self._observer.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        """Stop the observer and wait for it to finish."""
        self._observer.stop()
        self._observer.join()
        print("[file_watcher] stopped")
