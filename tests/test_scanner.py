import sys
from pathlib import Path

from space_map import ScanOptions, scan_tree


def allocated_bytes(path: Path) -> int:
    stat = path.stat()
    return stat.st_blocks * 512 if hasattr(stat, "st_blocks") else stat.st_size


def test_scan_tree_reports_root_and_nested_file_allocated_sizes(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    payload = nested / "payload.bin"
    payload.write_bytes(b"x" * 10_000)

    result = scan_tree(tmp_path, ScanOptions(threshold_bytes=1))

    assert result.root.path == tmp_path.resolve()
    assert result.root.allocated_bytes == allocated_bytes(payload)
    assert [child.name for child in result.root.children] == ["nested"]
    assert result.root.children[0].children[0].name == "payload.bin"
    assert result.root.children[0].children[0].allocated_bytes == allocated_bytes(payload)


def test_scan_tree_aggregates_small_direct_children_into_separate_misc_rows(tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.txt"
    dot_file = tmp_path / ".hidden"
    tiny.write_bytes(b"x")
    dot_file.write_bytes(b"y")
    threshold = allocated_bytes(tiny) + 1

    large_file = tmp_path / "large.bin"
    large_file.write_bytes(b"z" * (threshold * 3))

    small_directory = tmp_path / ".small-directory"
    small_directory.mkdir()
    small_payload = small_directory / "small.bin"
    small_payload.write_bytes(b"s")

    large_directory = tmp_path / "large-directory"
    large_directory.mkdir()
    large_payload = large_directory / "large.bin"
    large_payload.write_bytes(b"l" * (threshold * 3))

    result = scan_tree(tmp_path, ScanOptions(threshold_bytes=threshold))

    children_by_kind = {child.kind: child for child in result.root.children}
    assert children_by_kind["file"].name == "large.bin"
    assert children_by_kind["directory"].name == "large-directory"
    assert children_by_kind["misc_files"].name == "Misc files"
    assert children_by_kind["misc_files"].item_count == 2
    assert children_by_kind["misc_files"].allocated_bytes == (
        allocated_bytes(tiny) + allocated_bytes(dot_file)
    )
    assert children_by_kind["misc_directories"].name == "Misc directories"
    assert children_by_kind["misc_directories"].item_count == 1
    assert children_by_kind["misc_directories"].allocated_bytes == allocated_bytes(small_payload)
    assert result.root.allocated_bytes == sum(
        child.allocated_bytes for child in result.root.children
    )
    assert [child.allocated_bytes for child in result.root.children] == sorted(
        (child.allocated_bytes for child in result.root.children), reverse=True
    )


def test_scan_tree_progress_finishes_with_the_root_total_and_current_directory(
    tmp_path: Path,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    payload = child / "payload.bin"
    payload.write_bytes(b"content")
    updates = []

    result = scan_tree(tmp_path, ScanOptions(threshold_bytes=1), updates.append)

    assert len(updates) >= 2
    assert updates[-1].current_directory == tmp_path.resolve()
    assert updates[-1].allocated_bytes == result.root.allocated_bytes
    assert updates[-1].directories_scanned == 2
    assert updates[-1].files_scanned == 1
    assert [update.allocated_bytes for update in updates] == sorted(
        update.allocated_bytes for update in updates
    )


def test_scan_tree_reports_space_growth_while_enumerating_a_large_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "one.bin").write_bytes(b"one")
    (tmp_path / "two.bin").write_bytes(b"two")
    updates = []

    scan_tree(tmp_path, ScanOptions(threshold_bytes=1), updates.append)

    assert any(update.files_scanned == 1 and update.allocated_bytes > 0 for update in updates)


def test_scan_tree_does_not_follow_symlinks_and_counts_hard_links_once(tmp_path: Path) -> None:
    original = tmp_path / "original.bin"
    original.write_bytes(b"x" * 10_000)
    hard_link = tmp_path / "hard-link.bin"
    hard_link.hardlink_to(original)
    symlink = tmp_path / "symlink.bin"
    symlink.symlink_to(original)
    linked_directory = tmp_path / "linked-directory"
    linked_directory.symlink_to(tmp_path, target_is_directory=True)

    result = scan_tree(tmp_path, ScanOptions(threshold_bytes=1))

    assert result.root.allocated_bytes == allocated_bytes(original)
    assert result.files_scanned == 2
    assert len([child for child in result.root.children if child.kind == "file"]) == 1
    assert "symlink.bin" not in {child.name for child in result.root.children}
    assert "linked-directory" not in {child.name for child in result.root.children}


def test_scan_tree_returns_a_partial_result_when_a_directory_is_unreadable(tmp_path: Path) -> None:
    readable = tmp_path / "readable.bin"
    readable.write_bytes(b"visible")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "secret.bin").write_bytes(b"hidden")
    blocked.chmod(0)

    try:
        result = scan_tree(tmp_path, ScanOptions(threshold_bytes=1))
    finally:
        blocked.chmod(0o700)

    assert result.root.allocated_bytes == allocated_bytes(readable)
    assert result.root.incomplete is True
    assert len(result.warnings) == 1
    assert result.warnings[0].path == blocked.resolve()
    assert "Permission denied" in result.warnings[0].message


def test_scan_tree_excludes_a_requested_output_file(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"payload")
    old_report = tmp_path / "space-map-report.html"
    old_report.write_bytes(b"old report" * 1_000)

    result = scan_tree(
        tmp_path,
        ScanOptions(threshold_bytes=1, excluded_paths=(old_report,)),
    )

    assert result.root.allocated_bytes == allocated_bytes(payload)
    assert {child.name for child in result.root.children} == {"payload.bin"}


def test_scan_tree_handles_a_tree_deeper_than_python_recursion(tmp_path: Path) -> None:
    current = tmp_path
    for _ in range(400):
        current = current / "d"
        current.mkdir()
    payload = current / "x"
    payload.write_bytes(b"deep")

    previous_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(300)
        result = scan_tree(tmp_path, ScanOptions(threshold_bytes=1))
    finally:
        sys.setrecursionlimit(previous_limit)

    assert result.directories_scanned == 401
    assert result.root.allocated_bytes == allocated_bytes(payload)
