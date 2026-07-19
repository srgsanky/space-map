# Space Map Implementation Plan

## Goal

Build a read-only batch CLI named `space-map` that scans a selected directory tree, displays useful progress for a scan that may run for minutes, and atomically writes one self-contained HTML report.

The report will help a user identify the largest space consumers. Deleting, moving, or otherwise acting on files is explicitly out of scope.

## MVP decisions

These choices remove ambiguity from the first implementation:

- Scan one root directory supplied by the user; default to the current directory.
- Include dot files and dot directories. No name-based exclusions are applied.
- Measure **allocated bytes** using `st_blocks * 512`, falling back to logical `st_size` when allocated size is unavailable. This avoids badly overstating sparse files.
- Use binary scaling (`1 MB = 1024² bytes`) while displaying only `MB`, `GB`, or `TB`. Values larger than a TB remain expressed in TB; values below a MB remain expressed in MB.
- The visibility threshold is inclusive: a real file or directory is shown when its allocated size is `>= 100 MB`.
- The root is always shown, even when it is smaller than 100 MB.
- Synthetic `Misc directories` and `Misc files` rows are always allowed, regardless of their aggregate size.
- Do not follow symlinks. Ignore sockets, devices, FIFOs, and other non-regular entries.
- Count multiply-linked regular files once, keyed by device and inode. The first path encountered owns the bytes in the report. This makes the root total closer to actual consumed space than counting every hard-link path.
- Traverse each directory identity once, keyed by device and inode. The first path encountered owns the subtree, preventing aliases such as macOS `/Users` and `/System/Volumes/Data/Users` from being counted twice.
- Traverse mounted filesystems by default because they are part of the selected tree. Provide `--one-file-system` for users who want to stay on the root device. On macOS, skip external Time Machine backup volumes unless `--include-time-machine` is supplied.
- Continue through recoverable permission, race, and I/O errors. Mark the report partial and explain that its total is a lower bound.
- Use a sequential `os.scandir` traversal for MVP. Disk scans are generally I/O-bound, and uncontrolled concurrency can make rotational disks and network mounts slower. Parallel scanning can be considered only after profiling.
- Generate self-contained HTML using native `<details>`/`<summary>` branch controls and a small inline filtering script. The report needs no web server, CDN, or browser build tool.

## User interface

### Command

```bash
uv run space-map [ROOT] [OPTIONS]

# Examples
uv run space-map ./data
uv run space-map ./data --output ./disk-space-report.html
uv run space-map ./mounted-data --one-file-system
```

Initial options:

```text
ROOT                         Directory to scan; default: .
-o, --output PATH            Output file; default: ./space-map-report.html
--threshold-mb INTEGER       Visibility threshold; default: 100
--one-file-system            Do not descend onto a different device
--include-time-machine       Descend into external Time Machine backup volumes
--help
```

`--threshold-mb` keeps the required 100 MB default while allowing small, fast fixtures and occasional user customization. The normal interface remains one command with no configuration file.

### Terminal progress

While scanning, render these fields continuously:

```text
Scanning disk space
Elapsed       00:03:17
Current       <scan-root>/projects/example/cache/...
Found so far  183.4 GB
```

Implementation details:

- Use Rich `Live` output on a TTY.
- Update at most ten times per second by throttling display refreshes without throttling scan accounting.
- Derive elapsed time from `time.monotonic()`.
- “Found so far” is the deduplicated allocated size of regular files successfully statted so far. It only increases and equals the final root total after a complete scan.
- Show the directory currently being enumerated, not the last file.
- Also show small secondary counters for scanned directories, scanned files, and errors when space permits.
- For non-TTY output, emit a plain progress line at a slower interval (for example every five seconds) rather than terminal control sequences.
- On success, replace progress with a short summary containing total size, duration, warning count, and report path.
- On `Ctrl-C`, remove any temporary report, print an interrupted message, and exit with code 130. Do not present an incomplete report as complete.

## Report behavior

### Header

Show:

- `Space Map` title
- canonical root path
- total allocated size for the complete scanned tree
- scan start/completion timestamp and elapsed duration
- real files and directories scanned
- threshold and size-accounting method
- warning count and a prominent `Partial scan` badge when applicable

### Tree

The visual treatment should use these conventions:

- compact rows on a warm, quiet background
- thin connector lines between ancestors and children
- a small, explicit branch disclosure control
- monospaced paths/sizes and tabular numeric alignment
- sparse separators rather than nested cards
- accessible focus states and native keyboard interaction

Tree behavior:

- Render the root branch open initially.
- Render all other real directory branches collapsed initially.
- Clicking a directory’s native summary expands or collapses only that branch.
- Do not add “expand all” or “collapse all.”
- Filter rows by a case-insensitive name or full-path substring. Keep matching rows and their ancestors, dim non-matching ancestors, and automatically reveal matching paths while filtering.
- Provide a copy control beside each real file or directory name that copies its full path.
- Files and misc categories are leaves.
- Sort every directory’s displayed children by descending size. Use kind and case-folded name as deterministic tie-breakers.
- Sort synthetic misc rows by size alongside real children; a very large misc aggregate should be visible near the top rather than forced to the bottom.

Each row contains:

- file, directory, or aggregate marker
- basename (the root uses its canonical path)
- type/count detail, such as `directory`, `file`, or `1,842 direct files`
- percentage of its parent
- a subtle proportional usage bar
- formatted allocated size, right-aligned

A directory row’s size is its complete descendant-file allocation, not merely the visible children. A file row’s size is that file’s allocated size. Directory metadata blocks are intentionally excluded so every total can be reconciled from regular files.

### Threshold aggregation

Aggregation occurs independently at every displayed directory and only among its **direct** children:

1. A direct child directory whose complete subtree is at least the threshold is shown as a real directory row.
2. Smaller direct child directories are replaced by one `Misc directories` leaf containing their combined subtree size and count.
3. Direct child files at or above the threshold are shown as real file rows.
4. Smaller direct child files are replaced by one `Misc files` leaf containing their combined size and count.
5. Empty misc categories are omitted.

Example:

```text
- <scan-root>                                412.7 GB
  - projects                                 288.2 GB
    + example-app                            190.4 GB
      build-cache.bin                        112.0 GB
      Misc directories (96 direct dirs)       61.3 GB
      Misc files (8,240 direct files)          7.1 GB
    downloads                                 72.8 GB
    Misc directories (41 direct dirs)         18.9 GB
    Misc files (1,103 direct files)            6.1 GB
```

This preserves exact accounting at each directory without exposing individual entries below 100 MB.

### Warnings

If entries cannot be read or disappear during the scan:

- keep scanning siblings;
- increment the progress error count;
- mark the affected ancestor and final result incomplete;
- show a report warning explaining that totals may be low;
- show the bounded path/error examples in a collapsed-by-default tree so a pathological filesystem cannot make the report enormous;
- record the total suppressed-warning count when the bound is exceeded.

All paths and names must be HTML-escaped and must never be interpolated into the static filtering script. Filenames such as `<script>.bin` remain inert text.

## Module design

Keep the external seam small: the CLI validates arguments, calls the scanner once, and passes the result to the report writer. Scanner complexity remains behind one interface that tests and the CLI both use.

```python
result = scan_tree(root, ScanOptions(...), on_progress=callback)
write_html_report(result, output_path)
```

Suggested structure:

```text
space-map/
├── pyproject.toml
├── README.md
├── PLAN.md
├── src/
│   └── space_map/
│       ├── __init__.py
│       ├── cli.py              # Click command, Rich progress, exit behavior
│       ├── scanner.py          # iterative traversal and aggregation
│       ├── model.py            # ScanResult, ReportNode, warnings, progress DTOs
│       ├── report.py           # atomic self-contained HTML generation
│       ├── formatting.py       # MB/GB/TB and elapsed-time formatting
│       └── py.typed
└── tests/
    ├── test_cli.py
    ├── test_scanner.py
    ├── test_report.py
    └── test_formatting.py
```

Dependencies:

- Python 3.12+
- Click for the command interface
- Rich for terminal progress
- pytest and Ruff as development tools
- no frontend/runtime report dependencies

### Core model

```python
@dataclass(frozen=True)
class ReportNode:
    kind: Literal["root", "directory", "file", "misc_directories", "misc_files"]
    name: str
    path: Path | None
    allocated_bytes: int
    item_count: int
    incomplete: bool
    children: tuple["ReportNode", ...]

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
```

Keep raw byte counts in the model. Human formatting belongs at output edges so sorting, percentages, and tests never parse display strings.

## Scanner algorithm

Use an iterative post-order depth-first traversal to avoid Python recursion limits on unusually deep trees.

For each active directory frame, retain:

- canonical/display path and device
- running subtree bytes
- reportable direct files
- direct small-file byte/count aggregate
- completed reportable child directory nodes
- direct small-directory byte/count aggregate
- incomplete flag

Algorithm:

1. Resolve and validate the root; capture its device when `--one-file-system` is active.
2. Push a root frame and enumerate entries with `os.scandir`.
3. For a regular file, stat without following symlinks, apply hard-link deduplication when `st_nlink > 1`, add allocated bytes to global progress and the current frame, and retain a file node only when it reaches the threshold.
4. Aggregate smaller files immediately into the current frame’s misc-file counters.
5. For an eligible child directory, push a child frame and finish it before continuing the parent.
6. On child completion, return its full byte count to the parent. Retain its report subtree only if it reaches the threshold; otherwise discard its descendants and add its total/count to the parent’s misc-directory aggregate.
7. When a frame completes, create its two synthetic misc leaves when non-empty, sort its retained children, and return the compact result to its parent.
8. Always retain the final root frame and attach scan metadata/warnings.

This performs one filesystem traversal. It does not run `du` once per directory, which would repeatedly rescan descendants. Expected cost is O(number of visited entries), plus sorting retained direct children. Memory is proportional to the active traversal depth, retained report nodes, directory identities, and identities of multiply-linked files—not every small file path.

The output target is excluded from the scan when it is inside the selected root, preventing a prior report from counting itself.

## Atomic report writing

1. Create a temporary file beside the requested output.
2. Stream escaped HTML into it rather than building one giant string in memory.
3. Flush and close successfully.
4. Replace the destination with `os.replace`.
5. Remove the temporary file on any exception or interruption.

Streaming HTML also allows each completed model branch to be rendered without a second large in-memory serialization.

## Implementation sequence

### 1. Project foundation

- Add `pyproject.toml`, package layout, Click entry point, Ruff/pytest configuration, `.gitignore`, and a minimal README.
- Add formatting helpers and tests first, including the rule that only MB/GB/TB are emitted.
- Wire a placeholder command so `uv run space-map --help` works.

### 2. Filesystem inventory core

- Add model dataclasses and scanner options.
- Implement allocated-size calculation and regular-file classification.
- Implement iterative `os.scandir` traversal, symlink/special-file behavior, optional device restriction, and hard-link deduplication.
- Test nested totals, dot entries, sparse files where supported, symlinks, hard links, and exact-threshold behavior using a tiny configured test threshold.

### 3. Per-directory pruning and aggregation

- Add post-order directory completion.
- Add `Misc directories` and `Misc files` direct-child aggregates.
- Add deterministic descending-size ordering.
- Verify that every complete directory satisfies this invariant:

```text
directory total == sum(all displayed real children and misc category sizes)
```

- Verify that pruning a small directory discards its detailed descendants but preserves its full contribution to every ancestor total.

### 4. Progress and failure handling

- Emit `ScanProgress` snapshots from the scanner without coupling it to Rich.
- Add TTY live display, non-TTY periodic lines, elapsed time, current directory, and found bytes in the CLI adapter.
- Throttle rendering without throttling accounting.
- Add bounded warnings, incomplete propagation, interruption cleanup, and exit-code tests.

### 5. Static HTML report

- Implement semantic nested `<details>`/`<summary>` markup, self-contained CSS, and inline name-or-path filtering behavior.
- Apply a warm palette, compact rows, thin tree rails, plus/minus disclosure styling, visible focus states, and right-aligned metadata.
- Add header metadata, parent percentages, usage bars, partial-scan warnings, and print-friendly styles.
- Stream to a sibling temporary file and atomically replace the destination.
- Test escaping with Unicode, quotes, ampersands, and HTML-like filenames; test open root/closed descendants, filtering controls, row ordering, and absence of external resources.

### 6. End-to-end acceptance and documentation

- Run the CLI against a deterministic fixture tree and validate totals and report structure.
- Run a manual browser check in Safari, Chrome, and Firefox: open from `file://`, expand/collapse nested branches, keyboard-toggle summaries, verify long-path overflow, and print preview.
- Run a real-world directory scan and compare the root total directionally with a platform-appropriate disk-usage utility using allocated-byte semantics. Document expected differences caused by filesystem clones, compression, inaccessible entries, directory metadata, snapshots, and reclaimable space.
- Document installation, examples, size semantics, caveats, and report interpretation in README.

## Test matrix

### Scanner

- Empty root and root below threshold
- File exactly at, below, and above threshold
- Large directory made entirely of small direct files
- Large directory containing small and large child directories
- Separate misc-file and misc-directory aggregation at multiple levels
- Dot files and dot directories included
- Descending size and deterministic tie ordering
- Symlink to file and symlink to directory not followed
- Sparse file uses allocated size when supported
- Hard-linked file counted once
- `--one-file-system` skips a child on another device via a mocked stat/scandir seam
- Permission error, disappearing file, and unreadable directory produce a partial result
- Very deep tree does not hit recursion limits
- Existing output report is excluded

### Report

- Root total and metadata are present
- Root branch is open; nested branches are closed
- No expand-all/collapse-all controls exist
- Directory rows show complete subtree totals
- Misc labels show direct item counts
- Percentages and bars are clamped safely when a partial parent has zero bytes
- Only MB/GB/TB labels appear
- Filenames and warning text are escaped
- HTML has no external assets, supports case-insensitive name-or-path filtering with dimmed ancestors, and works from `file://`

### CLI

- Default root/output and explicit options
- Invalid root, invalid threshold, and unwritable destination errors
- Progress callback displays all three required fields
- Non-TTY progress is readable
- Success summary and exit code 0
- Fatal scan/report errors return nonzero
- `Ctrl-C` returns 130 and leaves no partial destination/temp file

## Acceptance criteria

- `uv run space-map <directory>` scans without modifying the tree and writes a self-contained HTML report.
- Dot entries are scanned without special configuration.
- Terminal progress continuously communicates elapsed time, current directory, and allocated space found so far.
- The report root shows total scanned allocated space.
- Every displayed directory shows its complete subtree size; every displayed file shows its allocated size.
- Real files/directories below 100 MB are absent as individual rows and are reconciled into separate misc categories at their direct parent.
- Siblings, including misc aggregates, appear largest first.
- Root starts expanded, nested directories can be independently expanded/collapsed, filtering retains and dims matching ancestors, and no global expansion controls exist.
- Every human-readable size uses only MB, GB, or TB.
- Recoverable scan errors produce a clearly partial but usable report; unsafe HTML names cannot alter the report.
- The scan is single-pass and report replacement is atomic.

## Explicitly out of scope

- deleting, moving, compressing, or recommending actions
- real-time filesystem watching or report refresh
- treemaps, charts, advanced query syntax, or global expansion controls
- a local HTTP server or hosted report
- reconciling snapshots, reclaimable space, deleted-open files, or filesystem-wide free-space reports
- following symlinks
- perfectly accounting for filesystem clones, compression, or remote-filesystem allocation semantics
- scan caches, incremental scans, or resume after interruption
