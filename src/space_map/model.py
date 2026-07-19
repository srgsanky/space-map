from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

NodeKind = Literal["root", "directory", "file", "misc_directories", "misc_files"]


@dataclass(frozen=True)
class ScanOptions:
    threshold_bytes: int = 100 * 1024 * 1024
    one_file_system: bool = False
    excluded_paths: tuple[Path, ...] = ()
    skip_time_machine_volumes: bool = True


@dataclass(frozen=True)
class ReportNode:
    kind: NodeKind
    name: str
    path: Path | None
    allocated_bytes: int
    item_count: int = 1
    incomplete: bool = False
    children: tuple[ReportNode, ...] = ()


@dataclass(frozen=True)
class ScanWarning:
    path: Path
    message: str


@dataclass(frozen=True)
class ScanProgress:
    current_directory: Path
    allocated_bytes: int
    directories_scanned: int
    files_scanned: int
    error_count: int


@dataclass(frozen=True)
class ScanResult:
    root: ReportNode
    started_at: datetime
    completed_at: datetime
    elapsed_seconds: float
    directories_scanned: int
    files_scanned: int
    warnings: tuple[ScanWarning, ...]
    suppressed_warning_count: int
    options: ScanOptions
