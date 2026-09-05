#!/usr/bin/env python3
"""Extract and rank likely reclaim candidates from a Space Map report."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

_GIB = 1024**3
_MIB = 1024**2
_MAC_DATA_PREFIX = "/System/Volumes/Data"


@dataclass(frozen=True)
class Node:
    path: str
    allocated_bytes: int
    kind: str


@dataclass(frozen=True)
class Report:
    source: str
    root_path: str
    allocated_bytes: int
    completed_at: str | None
    partial: bool
    threshold_bytes: int | None
    exact_sizes: bool
    nodes: tuple[Node, ...]


@dataclass(frozen=True)
class Rule:
    key: str
    title: str
    effort: int
    confidence: str
    safety: str
    priority_factor: float
    rationale: str
    action: str
    caveat: str
    matcher: Callable[[str], bool]


@dataclass(frozen=True)
class Finding:
    key: str
    title: str
    allocated_bytes: int
    effort: int
    confidence: str
    safety: str
    rationale: str
    action: str
    caveat: str
    paths: tuple[Node, ...]
    score: float


class _SpaceMapHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[Node] = []
        self.completed_at: str | None = None
        self.partial = False
        self._row: dict[str, Any] | None = None
        self._row_div_depth = 0
        self._capture: str | None = None
        self._capture_depth = 0
        self._in_partial_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())

        if tag == "time" and attributes.get("id") == "generated-time":
            self.completed_at = attributes.get("datetime")

        if tag == "span" and "warning-heading" in classes:
            self._in_partial_heading = True

        if self._row is not None:
            if tag == "div":
                self._row_div_depth += 1
            if tag == "span" and ("node-name" in classes or "node-size" in classes):
                self._capture = "name" if "node-name" in classes else "size"
                self._capture_depth = 1
            elif self._capture is not None:
                self._capture_depth += 1
            return

        if tag == "div" and "tree-node" in classes and attributes.get("data-path") is not None:
            self._row = {
                "path": attributes["data-path"],
                "name": "",
                "size": "",
                "kind": "file" if "node-leaf" in classes else "directory",
            }
            self._row_div_depth = 1

    def handle_data(self, data: str) -> None:
        if self._in_partial_heading and "Partial scan" in data:
            self.partial = True
        if self._row is not None and self._capture is not None:
            self._row[self._capture] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._in_partial_heading:
            self._in_partial_heading = False

        if self._row is None:
            return

        if self._capture is not None:
            self._capture_depth -= 1
            if self._capture_depth == 0:
                self._capture = None

        if tag == "div":
            self._row_div_depth -= 1
            if self._row_div_depth == 0:
                row = self._row
                self._row = None
                try:
                    allocated_bytes = _parse_display_size(row["size"])
                except ValueError:
                    return
                self.nodes.append(
                    Node(
                        path=row["path"],
                        allocated_bytes=allocated_bytes,
                        kind=row["kind"],
                    )
                )


def _logical_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized == _MAC_DATA_PREFIX:
        return "/"
    if normalized.startswith(f"{_MAC_DATA_PREFIX}/"):
        return normalized[len(_MAC_DATA_PREFIX) :]
    return normalized


def _parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in _logical_path(path).split("/") if part)


def _has_suffix(path: str, *suffix: str) -> bool:
    parts = _parts(path)
    return len(parts) >= len(suffix) and parts[-len(suffix) :] == suffix


def _basename(path: str) -> str:
    parts = _parts(path)
    return parts[-1] if parts else ""


def _is_user_generated_path(path: str) -> bool:
    parts = _parts(path)
    if len(parts) < 3 or parts[0] != "Users":
        return False
    tool_roots = {
        ".asdf",
        ".bun",
        ".cargo",
        ".local",
        ".npm",
        ".nvm",
        ".pyenv",
        ".rustup",
        ".volta",
        "Applications",
        "Library",
    }
    return parts[2] not in tool_roots


def _inside_app_bundle(path: str) -> bool:
    return any(part.endswith(".app") for part in _parts(path))


def _is_uv_cache(path: str) -> bool:
    return _has_suffix(path, ".cache", "uv") or _has_suffix(path, "Library", "Caches", "uv")


def _is_code_sign_clone(path: str) -> bool:
    logical = _logical_path(path)
    return (
        "/private/var/folders/" in logical
        and "/X/" in logical
        and _basename(path).endswith(".code_sign_clone")
    )


def _is_chrome_model(path: str) -> bool:
    parts = _parts(path)
    model_names = {
        "OptGuideOnDeviceModel",
        "OnDeviceModel",
        "OptimizationGuidePredictionModels",
    }
    return (
        bool(parts)
        and parts[-1] in model_names
        and "Application Support" in parts
        and any(browser in parts for browser in ("Chrome", "Chromium", "Brave-Browser"))
    )


def _is_browser_service_worker_cache(path: str) -> bool:
    parts = _parts(path)
    return (
        len(parts) >= 3
        and parts[-2:] == ("Service Worker", "CacheStorage")
        and "Application Support" in parts
        and any(browser in parts for browser in ("Chrome", "Chromium", "Brave-Browser"))
    )


def _is_jetbrains_cache(path: str) -> bool:
    return _has_suffix(path, "Library", "Caches", "JetBrains") or _has_suffix(
        path, ".cache", "JetBrains"
    )


def _is_jetbrains_log(path: str) -> bool:
    return _has_suffix(path, "Library", "Logs", "JetBrains")


def _is_old_jetbrains_data(path: str) -> bool:
    parts = _parts(path)
    return (
        len(parts) >= 2
        and parts[-2] == "JetBrains"
        and "Application Support" in parts
        and re.search(r"20\d{2}(?:\.\d+)?$", parts[-1]) is not None
    )


def _is_python_environment(path: str) -> bool:
    return _is_user_generated_path(path) and _parts(path)[-1] in {".venv", "venv", ".tox", ".nox"}


def _is_project_target(path: str) -> bool:
    return (
        _basename(path) == "target"
        and _is_user_generated_path(path)
        and not _inside_app_bundle(path)
    )


def _is_node_modules(path: str) -> bool:
    return (
        _basename(path) == "node_modules"
        and _is_user_generated_path(path)
        and not _inside_app_bundle(path)
    )


def _is_frontend_build(path: str) -> bool:
    return _basename(path) in {
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".parcel-cache",
        ".turbo",
    } and _is_user_generated_path(path)


def _is_playwright_cache(path: str) -> bool:
    return _has_suffix(path, "Library", "Caches", "ms-playwright") or _has_suffix(
        path, ".cache", "ms-playwright"
    )


def _is_homebrew_cache(path: str) -> bool:
    return _has_suffix(path, "Library", "Caches", "Homebrew")


def _is_developer_package_cache(path: str) -> bool:
    suffixes = (
        (".cache", "pip"),
        ("Library", "Caches", "pip"),
        (".cache", "huggingface"),
        (".cargo", "registry"),
        (".cargo", "git"),
        (".gradle", "caches"),
        (".m2", "repository"),
        ("go", "pkg", "mod"),
        ("Library", "pnpm", "store"),
        (".local", "share", "pnpm", "store"),
    )
    parts = _parts(path)
    if len(parts) >= 3 and parts[0] == "Users" and parts[-1] in {".npm", ".yarn"}:
        return len(parts) == 3
    return any(_has_suffix(path, *suffix) for suffix in suffixes)


def _is_xcode_derived_data(path: str) -> bool:
    return _has_suffix(path, "Library", "Developer", "Xcode", "DerivedData")


def _is_simulator_data(path: str) -> bool:
    return _has_suffix(path, "Library", "Developer", "CoreSimulator", "Devices") or _has_suffix(
        path, "Library", "Developer", "Xcode", "iOS DeviceSupport"
    )


def _is_google_updater(path: str) -> bool:
    return _has_suffix(path, "Library", "Application Support", "Google", "GoogleUpdater")


def _is_spotlight_index(path: str) -> bool:
    return _basename(path) == ".Spotlight-V100" or _has_suffix(
        path, "Library", "Metadata", "CoreSpotlight"
    )


def _is_user_application_cache(path: str) -> bool:
    parts = _parts(path)
    direct_user_cache = (
        len(parts) == 5 and parts[0] == "Users" and parts[2:4] == ("Library", "Caches")
    )
    direct_dot_cache = len(parts) == 4 and parts[0] == "Users" and parts[2] == ".cache"
    container_cache = (
        len(parts) == 8
        and parts[0] == "Users"
        and parts[2] == "Library"
        and parts[3] in {"Containers", "Group Containers"}
        and parts[-3:] == ("Data", "Library", "Caches")
    )
    return direct_user_cache or direct_dot_cache or container_cache


def _is_system_application_cache(path: str) -> bool:
    parts = _parts(path)
    return len(parts) == 3 and parts[:2] == ("Library", "Caches")


def _is_user_application_log(path: str) -> bool:
    parts = _parts(path)
    return len(parts) == 5 and parts[0] == "Users" and parts[2:4] == ("Library", "Logs")


def _is_temporary_item(path: str) -> bool:
    parts = _parts(path)
    var_folder_item = (
        len(parts) == 7 and parts[:3] == ("private", "var", "folders") and parts[5] in {"T", "X"}
    )
    private_tmp_item = len(parts) == 3 and parts[:2] == ("private", "tmp")
    return var_folder_item or private_tmp_item


def _is_docker_storage(path: str) -> bool:
    return _has_suffix(path, "Library", "Containers", "com.docker.docker", "Data", "vms")


def _is_trash(path: str) -> bool:
    parts = _parts(path)
    return bool(parts) and parts[-1] in {".Trash", ".Trashes"}


_RULES = (
    Rule(
        "uv-cache",
        "uv cache",
        1,
        "high",
        "routine",
        1.0,
        "Downloaded and unpacked Python artifacts are reproducible.",
        "Use `uv cache clean`; dependencies will be downloaded again when needed.",
        "The report size is a strong reclaim ceiling when no uv process is active.",
        _is_uv_cache,
    ),
    Rule(
        "code-sign-clones",
        "stale browser code-signing clones",
        2,
        "medium",
        "verify-stale",
        0.60,
        "Browser updates can leave large `*.code_sign_clone` trees in randomized macOS temp paths.",
        (
            "Quit the browser and updater, verify the clone is stale and unused, then remove only "
            "that clone."
        ),
        (
            "APFS shared extents can make visible allocation much larger than space actually "
            "reclaimed."
        ),
        _is_code_sign_clone,
    ),
    Rule(
        "chrome-models",
        "downloaded browser on-device models",
        1,
        "medium",
        "review",
        0.75,
        "Chrome-family browsers download versioned models that can be fetched again.",
        (
            "With the browser closed, remove only the identified model resource if re-download "
            "is acceptable."
        ),
        "Avoid broad deletion under browser Application Support; it contains profile data.",
        _is_chrome_model,
    ),
    Rule(
        "browser-service-worker-caches",
        "browser service-worker caches",
        2,
        "medium",
        "review",
        0.55,
        "Web applications can accumulate substantial CacheStorage data.",
        (
            "Prefer the browser's site-data controls; target only sites whose offline data can "
            "be rebuilt."
        ),
        "Clearing this can sign sites out or remove offline application data.",
        _is_browser_service_worker_cache,
    ),
    Rule(
        "jetbrains-cache",
        "JetBrains caches",
        1,
        "high",
        "routine",
        0.95,
        "IDE indexes and caches are regenerated.",
        (
            "Close JetBrains IDEs and use their cache invalidation/cleanup flow or clear the "
            "cache directory."
        ),
        "The first IDE restart can be slow while indexes rebuild.",
        _is_jetbrains_cache,
    ),
    Rule(
        "jetbrains-logs",
        "JetBrains logs",
        1,
        "high",
        "routine",
        0.90,
        "Historical IDE logs are usually expendable after active diagnostics are complete.",
        "Close the IDE and retain only logs needed for current investigations.",
        "Keep recent logs when debugging an IDE or plugin problem.",
        _is_jetbrains_log,
    ),
    Rule(
        "jetbrains-old-data",
        "versioned JetBrains application data",
        3,
        "medium",
        "review",
        0.30,
        "Multiple version directories can retain old plugins and state.",
        (
            "Compare with installed IDE versions and remove only versions no longer used, "
            "preferably via Toolbox."
        ),
        (
            "Current settings and plugins live here; the full listed size is not automatically "
            "reclaimable."
        ),
        _is_old_jetbrains_data,
    ),
    Rule(
        "python-environments",
        "Python virtual environments",
        2,
        "high",
        "rebuild-cost",
        0.90,
        (
            "Per-project environments duplicate packages and are reproducible when dependency "
            "files are current."
        ),
        (
            "Remove environments only in inactive projects with a lock/requirements file; "
            "recreate on demand."
        ),
        "Confirm local-only packages or manual environment changes are not needed.",
        _is_python_environment,
    ),
    Rule(
        "project-targets",
        "project `target` build directories",
        2,
        "high",
        "rebuild-cost",
        0.88,
        "Rust and Maven builds commonly place reproducible output in `target`.",
        "Verify the project type, then use its clean command (for Rust, `cargo clean`).",
        (
            "The next build pays the compilation cost; `target` can have other meanings outside "
            "projects."
        ),
        _is_project_target,
    ),
    Rule(
        "node-modules",
        "project node_modules directories",
        2,
        "high",
        "rebuild-cost",
        0.85,
        "Installed JavaScript dependencies are reproducible from a trustworthy lockfile.",
        (
            "Remove them in inactive projects and reinstall with that project's package manager "
            "when needed."
        ),
        "Confirm the lockfile is present and current before treating the directory as disposable.",
        _is_node_modules,
    ),
    Rule(
        "frontend-builds",
        "frontend generated build caches",
        1,
        "high",
        "rebuild-cost",
        0.90,
        "Framework-specific build and incremental caches are generated from source.",
        "Use the project's clean task or remove the identified generated directory.",
        "The next development/build run will regenerate it.",
        _is_frontend_build,
    ),
    Rule(
        "playwright-cache",
        "Playwright browser downloads",
        2,
        "high",
        "routine",
        0.85,
        "Automation browser binaries are versioned downloads.",
        "Use Playwright's uninstall command for unused browser versions, then reinstall on demand.",
        "Projects pinned to older Playwright versions may download those browsers again.",
        _is_playwright_cache,
    ),
    Rule(
        "homebrew-cache",
        "Homebrew download cache",
        1,
        "high",
        "routine",
        0.95,
        "Downloaded formula and cask artifacts can be fetched again.",
        "Use `brew cleanup` and review its output.",
        "Recent downloads may be useful for reinstalling while offline.",
        _is_homebrew_cache,
    ),
    Rule(
        "developer-package-caches",
        "developer package caches",
        2,
        "high",
        "routine",
        0.85,
        "Package registries and artifact caches are reproducible downloads.",
        "Use the owning package manager's cache prune/clean operation for each listed path.",
        "Future installs and builds will re-download artifacts.",
        _is_developer_package_cache,
    ),
    Rule(
        "xcode-derived-data",
        "Xcode DerivedData",
        1,
        "high",
        "rebuild-cost",
        0.95,
        "Build products and indexes in DerivedData are reproducible.",
        "Use Xcode's supported cleanup flow or remove stale per-project DerivedData.",
        "The next index and build will take longer.",
        _is_xcode_derived_data,
    ),
    Rule(
        "simulator-data",
        "Xcode simulator and device support data",
        3,
        "medium",
        "review",
        0.35,
        "Unavailable simulators and old device-support versions can accumulate.",
        "Use Xcode or `simctl` to remove unavailable runtimes/devices selectively.",
        (
            "Simulator application data may be valuable; the full listed size is not a reclaim "
            "estimate."
        ),
        _is_simulator_data,
    ),
    Rule(
        "google-updater",
        "Google updater data",
        2,
        "medium",
        "review",
        0.45,
        "Updater downloads and old versions can accumulate outside the browser cache.",
        "Inspect version/staging children and use the updater's supported cleanup path.",
        "Keep active updater components; broad removal may break automatic updates.",
        _is_google_updater,
    ),
    Rule(
        "spotlight-index",
        "Spotlight indexes",
        3,
        "medium",
        "system-managed",
        0.30,
        "A runaway index can become unusually large and is reproducible.",
        "Use macOS-supported Spotlight reindexing for the affected scope.",
        "Direct deletion is brittle, and reindexing temporarily consumes CPU, I/O, and space.",
        _is_spotlight_index,
    ),
    Rule(
        "application-caches",
        "application caches",
        2,
        "medium",
        "review",
        0.65,
        "Per-application cache roots often contain recreatable data.",
        "Start with the largest apps; quit each app and prefer its built-in cache controls.",
        (
            "Review each path independently because some apps misuse cache locations for durable "
            "state."
        ),
        _is_user_application_cache,
    ),
    Rule(
        "system-application-caches",
        "system-wide application caches",
        3,
        "medium",
        "review",
        0.35,
        "Shared application updaters and installers can leave sizable caches.",
        "Identify the owning application and use its cleanup/uninstall flow.",
        "These paths may require administrator access and can serve multiple users.",
        _is_system_application_cache,
    ),
    Rule(
        "application-logs",
        "application logs",
        1,
        "medium",
        "review",
        0.70,
        "Old logs can grow without helping normal application operation.",
        "Retain recent diagnostic material and remove or rotate older logs with the app closed.",
        "Logs may be needed for active support or incident investigations.",
        _is_user_application_log,
    ),
    Rule(
        "temporary-items",
        "large temporary items",
        2,
        "medium",
        "verify-stale",
        0.45,
        "macOS and applications place transient work under randomized temp roots.",
        (
            "Verify ownership, age, and that no process uses each item; a reboot may clear valid "
            "stale items."
        ),
        "Active temporary files can be unsafe to remove, and APFS sharing can overstate reclaim.",
        _is_temporary_item,
    ),
    Rule(
        "docker-storage",
        "Docker virtual-machine storage",
        3,
        "medium",
        "tool-managed",
        0.25,
        "Unused images, containers, and volumes can consume space inside Docker's VM.",
        (
            "Inspect with Docker's disk-usage commands and prune selected unused objects through "
            "Docker."
        ),
        "The VM file's allocated size is not the amount a prune will return to macOS.",
        _is_docker_storage,
    ),
    Rule(
        "trash",
        "Trash",
        1,
        "high",
        "personal-review",
        0.65,
        "Items already moved to Trash are often the lowest-effort reclaim opportunity.",
        "Review the contents, then empty Trash through the operating system.",
        "Emptying Trash permanently removes personal files.",
        _is_trash,
    ),
)


def _parse_display_size(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s+(MB|GB|TB)\s*", value)
    if match is None:
        raise ValueError(f"unsupported Space Map size: {value!r}")
    factors = {"MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return round(float(match.group(1)) * factors[match.group(2)])


def _load_json_report(path: Path) -> Report:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("format") != "space-map" or document.get("schema_version") != 1:
        raise ValueError("unsupported Space Map JSON format or schema version")
    scan = document.get("scan")
    raw_nodes = document.get("nodes")
    if not isinstance(scan, dict) or not isinstance(raw_nodes, list):
        raise ValueError("invalid Space Map JSON report")

    nodes: list[Node] = []
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict) or raw_node.get("path") is None:
            continue
        allocated_bytes = raw_node.get("allocated_bytes")
        if not isinstance(allocated_bytes, int) or allocated_bytes < 0:
            raise ValueError("invalid allocated_bytes in Space Map JSON report")
        nodes.append(
            Node(
                path=str(raw_node["path"]),
                allocated_bytes=allocated_bytes,
                kind=str(raw_node.get("kind", "unknown")),
            )
        )
    if not nodes:
        raise ValueError("Space Map JSON report has no real nodes")

    return Report(
        source=str(path),
        root_path=str(scan.get("root_path", nodes[0].path)),
        allocated_bytes=nodes[0].allocated_bytes,
        completed_at=str(scan["completed_at"]) if scan.get("completed_at") else None,
        partial=bool(scan.get("partial", False)),
        threshold_bytes=(
            int(scan["threshold_bytes"]) if scan.get("threshold_bytes") is not None else None
        ),
        exact_sizes=True,
        nodes=tuple(nodes),
    )


def _load_html_report(path: Path) -> Report:
    parser = _SpaceMapHTMLParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    if not parser.nodes:
        raise ValueError("HTML file does not contain a Space Map report tree")
    root = parser.nodes[0]
    return Report(
        source=str(path),
        root_path=root.path,
        allocated_bytes=root.allocated_bytes,
        completed_at=parser.completed_at,
        partial=parser.partial,
        threshold_bytes=None,
        exact_sizes=False,
        nodes=tuple(parser.nodes),
    )


def _load_report(path: Path) -> Report:
    if not path.is_file():
        raise ValueError(f"report does not exist or is not a file: {path}")
    if path.suffix.casefold() == ".json":
        return _load_json_report(path)
    return _load_html_report(path)


def _path_depth(path: str) -> int:
    return len(_parts(path))


def _is_same_or_descendant(path: str, ancestor: str) -> bool:
    candidate = _logical_path(path).rstrip("/") or "/"
    root = _logical_path(ancestor).rstrip("/") or "/"
    return candidate == root or (root != "/" and candidate.startswith(f"{root}/"))


def _collect_findings(report: Report) -> tuple[tuple[Finding, ...], tuple[Node, ...]]:
    targets: list[tuple[Node, Rule]] = []
    for node in report.nodes:
        if node.path == report.root_path:
            continue
        for rule in _RULES:
            if rule.matcher(node.path):
                targets.append((node, rule))
                break

    selected: list[tuple[Node, Rule]] = []
    for node, rule in sorted(
        targets, key=lambda item: (_path_depth(item[0].path), -item[0].allocated_bytes)
    ):
        if any(_is_same_or_descendant(node.path, kept.path) for kept, _ in selected):
            continue
        selected.append((node, rule))

    grouped: dict[str, list[Node]] = defaultdict(list)
    rules_by_key = {rule.key: rule for rule in _RULES}
    for node, rule in selected:
        grouped[rule.key].append(node)

    findings: list[Finding] = []
    for key, paths in grouped.items():
        rule = rules_by_key[key]
        allocated_bytes = sum(path.allocated_bytes for path in paths)
        findings.append(
            Finding(
                key=key,
                title=rule.title,
                allocated_bytes=allocated_bytes,
                effort=rule.effort,
                confidence=rule.confidence,
                safety=rule.safety,
                rationale=rule.rationale,
                action=rule.action,
                caveat=rule.caveat,
                paths=tuple(sorted(paths, key=lambda path: -path.allocated_bytes)),
                score=allocated_bytes * rule.priority_factor / rule.effort,
            )
        )
    findings.sort(key=lambda finding: (-finding.score, -finding.allocated_bytes, finding.title))
    return tuple(findings), tuple(node for node, _ in selected)


def _unclassified_endpoints(
    report: Report, selected: Sequence[Node], *, limit: int
) -> tuple[Node, ...]:
    paths = {_logical_path(node.path).rstrip("/") or "/" for node in report.nodes}
    paths_with_descendants: set[str] = set()
    for path in paths:
        parent = path.rsplit("/", 1)[0] or "/"
        while parent != "/":
            if parent in paths:
                paths_with_descendants.add(parent)
            parent = parent.rsplit("/", 1)[0] or "/"

    endpoints: list[Node] = []
    for node in report.nodes:
        logical = _logical_path(node.path).rstrip("/") or "/"
        if logical in paths_with_descendants:
            continue
        if any(_is_same_or_descendant(node.path, target.path) for target in selected):
            continue
        if logical == _logical_path(report.root_path).rstrip("/"):
            continue
        if logical.startswith(("/System/", "/usr/", "/bin/", "/sbin/")):
            continue
        if _inside_app_bundle(node.path) and not logical.endswith(".app"):
            continue
        if not logical.startswith(("/Users/", "/private/", "/Applications/", "/Library/")):
            continue
        if node.allocated_bytes < 100 * _MIB:
            continue
        endpoints.append(node)
    endpoints.sort(key=lambda node: -node.allocated_bytes)
    return tuple(endpoints[:limit])


def _format_size(size: int) -> str:
    if size >= 1024**4:
        return f"{size / 1024**4:.1f} TB"
    if size >= _GIB:
        return f"{size / _GIB:.1f} GB"
    return f"{size / _MIB:.1f} MB"


def _markdown(
    report: Report,
    findings: Sequence[Finding],
    unknown: Sequence[Node],
    *,
    top_paths: int,
) -> str:
    precision = (
        "exact bytes" if report.exact_sizes else "sizes reconstructed from rounded HTML labels"
    )
    lines = [
        "# Space Map reclaim analysis",
        "",
        f"- Source: {json.dumps(report.source, ensure_ascii=False)}",
        f"- Scan root: {json.dumps(report.root_path, ensure_ascii=False)}",
        f"- Visible allocation: **{_format_size(report.allocated_bytes)}** ({precision})",
        f"- Completed: {report.completed_at or 'unknown'}",
        f"- Scan status: {'partial — totals are a lower bound' if report.partial else 'complete'}",
    ]
    if report.threshold_bytes is not None:
        lines.append(f"- Visibility threshold: {_format_size(report.threshold_bytes)}")
    lines.extend(
        [
            (
                "- Interpretation: candidate sizes are reclaim ceilings, not guarantees; "
                "candidate roots do not overlap."
            ),
            "",
            "## Ranked recognized candidates",
            "",
            "| Rank | Candidate | Visible allocation | Effort | Confidence | Handling | Paths |",
            "|---:|---|---:|---:|---|---|---:|",
        ]
    )
    for index, finding in enumerate(findings, start=1):
        lines.append(
            f"| {index} | {finding.title} | {_format_size(finding.allocated_bytes)} | "
            f"{finding.effort}/3 | {finding.confidence} | {finding.safety} | {len(finding.paths)} |"
        )
    if not findings:
        lines.append("| — | No recognized candidate signatures | — | — | — | — | — |")

    for index, finding in enumerate(findings, start=1):
        lines.extend(
            [
                "",
                f"### {index}. {finding.title}",
                "",
                (
                    f"- **Visible allocation:** {_format_size(finding.allocated_bytes)} across "
                    f"{len(finding.paths)} path(s)"
                ),
                f"- **Why:** {finding.rationale}",
                f"- **Preferred action:** {finding.action}",
                f"- **Caveat:** {finding.caveat}",
                "- **Largest paths:**",
            ]
        )
        for node in finding.paths[:top_paths]:
            display_path = json.dumps(_logical_path(node.path), ensure_ascii=False)
            lines.append(f"  - {_format_size(node.allocated_bytes)} — {display_path}")
        omitted = len(finding.paths) - top_paths
        if omitted > 0:
            lines.append(f"  - … {omitted} more path(s)")

    lines.extend(
        [
            "",
            "## Largest unclassified endpoints (manual review only)",
            "",
            (
                "These are investigation leads, not cleanup recommendations. Their contents may "
                "be durable or personal data."
            ),
        ]
    )
    if unknown:
        for node in unknown:
            display_path = json.dumps(_logical_path(node.path), ensure_ascii=False)
            lines.append(f"- {_format_size(node.allocated_bytes)} — {display_path}")
    else:
        lines.append("- None above the reporting cutoff.")
    return "\n".join(lines) + "\n"


def _json_output(report: Report, findings: Sequence[Finding], unknown: Sequence[Node]) -> str:
    payload = {
        "report": {
            "source": report.source,
            "root_path": report.root_path,
            "allocated_bytes": report.allocated_bytes,
            "completed_at": report.completed_at,
            "partial": report.partial,
            "threshold_bytes": report.threshold_bytes,
            "exact_sizes": report.exact_sizes,
        },
        "findings": [
            {
                **{
                    key: value
                    for key, value in asdict(finding).items()
                    if key not in {"paths", "score"}
                },
                "paths": [asdict(path) for path in finding.paths],
            }
            for finding in findings
        ],
        "unclassified_endpoints": [asdict(node) for node in unknown],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank likely reclaim candidates in a Space Map HTML or JSON report."
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--top-paths", type=int, default=8)
    parser.add_argument("--top-unclassified", type=int, default=10)
    args = parser.parse_args()
    if args.top_paths < 1 or args.top_unclassified < 0:
        parser.error("--top-paths must be positive and --top-unclassified must not be negative")
    return args


def main() -> int:
    args = _parse_args()
    try:
        report = _load_report(args.report.expanduser().resolve(strict=False))
        findings, selected = _collect_findings(report)
        unknown = _unclassified_endpoints(report, selected, limit=args.top_unclassified)
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(f"error: {error}") from error

    if args.format == "json":
        print(_json_output(report, findings, unknown), end="")
    else:
        print(
            _markdown(report, findings, unknown, top_paths=args.top_paths),
            end="",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
