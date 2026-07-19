from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .model import ReportNode, ScanOptions, ScanProgress, ScanResult, ScanWarning
from .volumes import is_external_time_machine_volume

ProgressCallback = Callable[[ScanProgress], None]
_MAX_RETAINED_WARNINGS = 100


@dataclass
class _DirectoryFrame:
    path: Path
    device: int
    is_root: bool
    entries: Iterator[os.DirEntry[str]] | None
    children: list[ReportNode] = field(default_factory=list)
    total: int = 0
    misc_file_bytes: int = 0
    misc_file_count: int = 0
    misc_directory_bytes: int = 0
    misc_directory_count: int = 0
    incomplete: bool = False


def scan_tree(
    root: Path | str,
    options: ScanOptions | None = None,
    on_progress: ProgressCallback | None = None,
) -> ScanResult:
    options = options or ScanOptions()
    root_path = Path(root).expanduser().resolve(strict=True)
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)
    if options.threshold_bytes < 0:
        raise ValueError("threshold_bytes must not be negative")

    excluded_paths = {path.expanduser().resolve(strict=False) for path in options.excluded_paths}
    root_stat = root_path.stat()
    root_device = root_stat.st_dev
    started_at = datetime.now().astimezone()
    started_clock = time.monotonic()
    directories_scanned = 0
    files_scanned = 0
    allocated_so_far = 0
    error_count = 0
    suppressed_warning_count = 0
    warnings: list[ScanWarning] = []
    seen_directories = {(root_stat.st_dev, root_stat.st_ino)}
    seen_hard_links: set[tuple[int, int]] = set()

    def progress(directory: Path) -> None:
        if on_progress is not None:
            on_progress(
                ScanProgress(
                    current_directory=directory,
                    allocated_bytes=allocated_so_far,
                    directories_scanned=directories_scanned,
                    files_scanned=files_scanned,
                    error_count=error_count,
                )
            )

    def record_warning(path: Path, error: OSError) -> None:
        nonlocal error_count, suppressed_warning_count
        error_count += 1
        if len(warnings) < _MAX_RETAINED_WARNINGS:
            warnings.append(ScanWarning(path=path, message=str(error)))
        else:
            suppressed_warning_count += 1

    def start_directory(path: Path, device: int, *, is_root: bool = False) -> _DirectoryFrame:
        nonlocal directories_scanned
        directories_scanned += 1
        try:
            entries: Iterator[os.DirEntry[str]] | None = os.scandir(path)
            frame = _DirectoryFrame(path=path, device=device, is_root=is_root, entries=entries)
        except OSError as error:
            record_warning(path, error)
            frame = _DirectoryFrame(
                path=path,
                device=device,
                is_root=is_root,
                entries=None,
                incomplete=True,
            )
        progress(path)
        return frame

    def complete_directory(frame: _DirectoryFrame) -> ReportNode:
        if frame.misc_directory_count:
            frame.children.append(
                ReportNode(
                    kind="misc_directories",
                    name="Misc directories",
                    path=None,
                    allocated_bytes=frame.misc_directory_bytes,
                    item_count=frame.misc_directory_count,
                )
            )
        if frame.misc_file_count:
            frame.children.append(
                ReportNode(
                    kind="misc_files",
                    name="Misc files",
                    path=None,
                    allocated_bytes=frame.misc_file_bytes,
                    item_count=frame.misc_file_count,
                )
            )
        frame.children.sort(
            key=lambda child: (-child.allocated_bytes, child.kind, child.name.casefold())
        )
        progress(frame.path)
        return ReportNode(
            kind="root" if frame.is_root else "directory",
            name=str(frame.path) if frame.is_root else frame.path.name,
            path=frame.path,
            allocated_bytes=frame.total,
            incomplete=frame.incomplete,
            children=tuple(frame.children),
        )

    def attach_directory(parent: _DirectoryFrame, child: ReportNode) -> None:
        parent.incomplete = parent.incomplete or child.incomplete
        parent.total += child.allocated_bytes
        if child.allocated_bytes >= options.threshold_bytes:
            parent.children.append(child)
        else:
            parent.misc_directory_bytes += child.allocated_bytes
            parent.misc_directory_count += 1

    stack = [start_directory(root_path, root_device, is_root=True)]
    root_node: ReportNode | None = None

    try:
        while stack:
            frame = stack[-1]
            if frame.entries is None:
                stack.pop()
                completed = complete_directory(frame)
                if stack:
                    attach_directory(stack[-1], completed)
                else:
                    root_node = completed
                continue

            try:
                entry = next(frame.entries)
            except StopIteration:
                frame.entries.close()
                frame.entries = None
                continue
            except OSError as error:
                record_warning(frame.path, error)
                frame.incomplete = True
                frame.entries.close()
                frame.entries = None
                continue

            path = Path(entry.path)
            if path in excluded_paths:
                continue

            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    directory_stat = entry.stat(follow_symlinks=False)
                    identity = (directory_stat.st_dev, directory_stat.st_ino)
                    if identity in seen_directories:
                        continue
                    if options.one_file_system and directory_stat.st_dev != root_device:
                        continue
                    crosses_mount = directory_stat.st_dev != frame.device
                    if (
                        options.skip_time_machine_volumes
                        and crosses_mount
                        and is_external_time_machine_volume(path)
                    ):
                        continue
                    seen_directories.add(identity)
                    stack.append(start_directory(path, directory_stat.st_dev))
                elif entry.is_file(follow_symlinks=False):
                    stat_result = entry.stat(follow_symlinks=False)
                    allocated = _allocated_bytes(stat_result)
                    if stat_result.st_nlink > 1:
                        identity = (stat_result.st_dev, stat_result.st_ino)
                        if identity in seen_hard_links:
                            allocated = 0
                        else:
                            seen_hard_links.add(identity)
                    files_scanned += 1
                    allocated_so_far += allocated
                    frame.total += allocated
                    if allocated >= options.threshold_bytes:
                        frame.children.append(
                            ReportNode(
                                kind="file",
                                name=entry.name,
                                path=path,
                                allocated_bytes=allocated,
                            )
                        )
                    else:
                        frame.misc_file_bytes += allocated
                        frame.misc_file_count += 1
                    progress(frame.path)
            except OSError as error:
                frame.incomplete = True
                record_warning(path, error)
    finally:
        for frame in stack:
            if frame.entries is not None:
                frame.entries.close()

    if root_node is None:  # pragma: no cover - defensive invariant
        raise RuntimeError("scan completed without a root result")

    completed_at = datetime.now().astimezone()
    return ScanResult(
        root=root_node,
        started_at=started_at,
        completed_at=completed_at,
        elapsed_seconds=time.monotonic() - started_clock,
        directories_scanned=directories_scanned,
        files_scanned=files_scanned,
        warnings=tuple(warnings),
        suppressed_warning_count=suppressed_warning_count,
        options=options,
    )


def _allocated_bytes(stat_result: os.stat_result) -> int:
    blocks = getattr(stat_result, "st_blocks", None)
    return blocks * 512 if blocks is not None else stat_result.st_size
