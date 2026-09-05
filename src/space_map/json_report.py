from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .model import ReportNode, ScanResult

SCHEMA_VERSION = 1


def write_json_report(result: ScanResult, output_path: Path | str) -> None:
    """Atomically write the visible report tree as machine-readable JSON."""
    output = Path(output_path).expanduser().resolve(strict=False)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            json.dump(_report_document(result), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _report_document(result: ScanResult) -> dict[str, Any]:
    partial = result.root.incomplete or bool(result.warnings) or result.suppressed_warning_count > 0
    return {
        "format": "space-map",
        "schema_version": SCHEMA_VERSION,
        "scan": {
            "root_path": str(result.root.path)
            if result.root.path is not None
            else result.root.name,
            "started_at": result.started_at.isoformat(),
            "completed_at": result.completed_at.isoformat(),
            "elapsed_seconds": result.elapsed_seconds,
            "directories_scanned": result.directories_scanned,
            "files_scanned": result.files_scanned,
            "partial": partial,
            "suppressed_warning_count": result.suppressed_warning_count,
            "threshold_bytes": result.options.threshold_bytes,
            "one_file_system": result.options.one_file_system,
            "included_time_machine_volumes": not result.options.skip_time_machine_volumes,
            "size_semantics": "allocated_regular_file_bytes",
        },
        "nodes": _flatten_nodes(result.root),
        "warnings": [
            {"path": str(warning.path), "message": warning.message} for warning in result.warnings
        ],
    }


def _flatten_nodes(root: ReportNode) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    stack: list[tuple[ReportNode, int | None]] = [(root, None)]
    while stack:
        node, parent_id = stack.pop()
        node_id = len(nodes)
        nodes.append(
            {
                "id": node_id,
                "parent_id": parent_id,
                "kind": node.kind,
                "name": node.name,
                "path": str(node.path) if node.path is not None else None,
                "allocated_bytes": node.allocated_bytes,
                "item_count": node.item_count,
                "incomplete": node.incomplete,
            }
        )
        for child in reversed(node.children):
            stack.append((child, node_id))
    return nodes
