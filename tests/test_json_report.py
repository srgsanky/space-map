import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from space_map import ReportNode, ScanOptions, ScanResult, ScanWarning, write_json_report


def test_write_json_report_preserves_exact_sizes_paths_and_scan_metadata(tmp_path: Path) -> None:
    started = datetime(2026, 7, 18, 12, 0, 0, 123456, tzinfo=UTC)
    child_path = tmp_path / "nested & things"
    result = ScanResult(
        root=ReportNode(
            kind="root",
            name=str(tmp_path),
            path=tmp_path,
            allocated_bytes=2 * 1024**3 + 17,
            incomplete=True,
            children=(
                ReportNode(
                    kind="directory",
                    name=child_path.name,
                    path=child_path,
                    allocated_bytes=2 * 1024**3 + 17,
                    children=(
                        ReportNode(
                            kind="misc_files",
                            name="Misc files",
                            path=None,
                            allocated_bytes=17,
                            item_count=3,
                        ),
                    ),
                ),
            ),
        ),
        started_at=started,
        completed_at=started + timedelta(seconds=90),
        elapsed_seconds=90.25,
        directories_scanned=2,
        files_scanned=3,
        warnings=(ScanWarning(path=tmp_path / "protected", message="Permission denied"),),
        suppressed_warning_count=4,
        options=ScanOptions(
            threshold_bytes=25 * 1024**2,
            one_file_system=True,
            skip_time_machine_volumes=False,
        ),
    )
    output = tmp_path / "report.json"

    write_json_report(result, output)

    document = json.loads(output.read_text())
    assert document["format"] == "space-map"
    assert document["schema_version"] == 1
    assert document["scan"] == {
        "root_path": str(tmp_path),
        "started_at": started.isoformat(),
        "completed_at": (started + timedelta(seconds=90)).isoformat(),
        "elapsed_seconds": 90.25,
        "directories_scanned": 2,
        "files_scanned": 3,
        "partial": True,
        "suppressed_warning_count": 4,
        "threshold_bytes": 25 * 1024**2,
        "one_file_system": True,
        "included_time_machine_volumes": True,
        "size_semantics": "allocated_regular_file_bytes",
    }
    assert document["nodes"] == [
        {
            "id": 0,
            "parent_id": None,
            "kind": "root",
            "name": str(tmp_path),
            "path": str(tmp_path),
            "allocated_bytes": 2 * 1024**3 + 17,
            "item_count": 1,
            "incomplete": True,
        },
        {
            "id": 1,
            "parent_id": 0,
            "kind": "directory",
            "name": "nested & things",
            "path": str(child_path),
            "allocated_bytes": 2 * 1024**3 + 17,
            "item_count": 1,
            "incomplete": False,
        },
        {
            "id": 2,
            "parent_id": 1,
            "kind": "misc_files",
            "name": "Misc files",
            "path": None,
            "allocated_bytes": 17,
            "item_count": 3,
            "incomplete": False,
        },
    ]
    assert document["warnings"] == [
        {"path": str(tmp_path / "protected"), "message": "Permission denied"}
    ]
