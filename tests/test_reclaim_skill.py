import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from space_map import ReportNode, ScanOptions, ScanResult, write_html_report

_ANALYZER = (
    Path(__file__).parents[1]
    / ".agents"
    / "skills"
    / "space-map-reclaim"
    / "scripts"
    / "analyze_report.py"
)


def _analyze(report: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(_ANALYZER), str(report), "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_reclaim_analyzer_groups_generated_data_and_matches_randomized_code_sign_paths(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report.json"
    code_sign_path = (
        "/System/Volumes/Data/private/var/folders/zz/another-random-value/X/"
        "com.google.Chrome.code_sign_clone"
    )
    nodes = [
        _json_node(0, None, "root", "/", 100 * 1024**3),
        _json_node(1, 0, "directory", "/Users/alice/.cache/uv", 20 * 1024**3),
        _json_node(2, 0, "directory", code_sign_path, 8 * 1024**3),
        _json_node(3, 0, "directory", "/Users/alice/code/one/.venv", 2 * 1024**3),
        _json_node(4, 0, "directory", "/Users/alice/code/two/.venv", 3 * 1024**3),
        _json_node(5, 0, "directory", "/Users/alice/code/rust/target", 4 * 1024**3),
        _json_node(
            6,
            0,
            "directory",
            "/Users/alice/.nvm/versions/node/v22/lib/node_modules",
            2 * 1024**3,
        ),
    ]
    report_path.write_text(
        json.dumps(
            {
                "format": "space-map",
                "schema_version": 1,
                "scan": {
                    "root_path": "/",
                    "completed_at": "2026-01-01T00:00:00+00:00",
                    "partial": False,
                    "threshold_bytes": 100 * 1024**2,
                },
                "nodes": nodes,
                "warnings": [],
            }
        )
    )

    analysis = _analyze(report_path)

    findings = {finding["key"]: finding for finding in analysis["findings"]}
    assert findings["uv-cache"]["allocated_bytes"] == 20 * 1024**3
    assert findings["code-sign-clones"]["paths"][0]["path"] == code_sign_path
    assert findings["python-environments"]["allocated_bytes"] == 5 * 1024**3
    assert findings["project-targets"]["allocated_bytes"] == 4 * 1024**3
    assert "node-modules" not in findings
    assert analysis["report"]["exact_sizes"] is True


def test_reclaim_analyzer_accepts_existing_html_reports(tmp_path: Path) -> None:
    code_sign_path = (
        tmp_path
        / "private"
        / "var"
        / "folders"
        / "ab"
        / "random"
        / "X"
        / "com.brave.Browser.code_sign_clone"
    )
    started = datetime(2026, 1, 1, tzinfo=UTC)
    result = ScanResult(
        root=ReportNode(
            kind="root",
            name="/",
            path=Path("/"),
            allocated_bytes=2 * 1024**3,
            children=(
                ReportNode(
                    kind="directory",
                    name=code_sign_path.name,
                    path=Path(
                        "/System/Volumes/Data/private/var/folders/ab/random/X/"
                        "com.brave.Browser.code_sign_clone"
                    ),
                    allocated_bytes=2 * 1024**3,
                ),
            ),
        ),
        started_at=started,
        completed_at=started,
        elapsed_seconds=0,
        directories_scanned=2,
        files_scanned=1,
        warnings=(),
        suppressed_warning_count=0,
        options=ScanOptions(),
    )
    report_path = tmp_path / "report.html"
    write_html_report(result, report_path)

    analysis = _analyze(report_path)

    assert analysis["report"]["exact_sizes"] is False
    assert analysis["findings"][0]["key"] == "code-sign-clones"


def _json_node(
    node_id: int,
    parent_id: int | None,
    kind: str,
    path: str,
    allocated_bytes: int,
) -> dict[str, object]:
    return {
        "id": node_id,
        "parent_id": parent_id,
        "kind": kind,
        "name": Path(path).name,
        "path": path,
        "allocated_bytes": allocated_bytes,
        "item_count": 1,
        "incomplete": False,
    }
