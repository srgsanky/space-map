# Space Map

`space-map` is a read-only batch utility that scans a directory tree and writes a self-contained, collapsible HTML disk-space report. It is intended to show where most allocated space is consumed; cleanup actions are left to the user.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Finding what is filling a Mac

Start with a report of the whole Mac to find the largest areas:

```bash
uv run space-map / --output ~/Desktop/space-map-mac.html
open ~/Desktop/space-map-mac.html
```

Then generate more focused reports for common hot spots. A lower threshold makes these reports more detailed:

```bash
# Your files, downloads, caches, and application data
uv run space-map "$HOME" --threshold-mb 25 \
  --output ~/Desktop/space-map-home.html

# Temporary files (/tmp resolves to /private/tmp on macOS)
uv run space-map /private/tmp --threshold-mb 25 \
  --output ~/Desktop/space-map-tmp.html
```

Open the focused reports and expand the largest rows first. Space Map is read-only: review anything it identifies before deleting it with the Finder or an appropriate application.

A scan of `/` can be marked **Partial scan** when macOS denies access to protected locations. Granting Full Disk Access to the terminal application running Space Map can make the report more complete. Do not use `--one-file-system` for this whole-Mac scan: modern macOS installations split system and user data across volumes.

## Usage

```bash
# Scan the current directory and write ./space-map-report.html
uv run space-map

# Scan a specific tree
uv run space-map ~

# Choose the destination
uv run space-map / --output ~/Desktop/disk-space-report.html

# Avoid crossing onto another mounted filesystem
uv run space-map /Volumes/Data --one-file-system

# Include external Time Machine backup volumes (skipped by default on macOS)
uv run space-map / --include-time-machine

# Change the per-entry threshold (the default is 100 MB)
uv run space-map ~/workspace --threshold-mb 250
```

Install it as a standalone tool if desired:

```bash
uv tool install .
space-map ~ --output ~/Desktop/space-map-report.html
```

Run `space-map --help` for all options.

## What the report shows

- The root row always shows the allocated size of the complete scanned tree.
- Real files and directories are shown individually when they are at least 100 MB by default.
- Smaller direct child directories are combined into `Misc directories` at each parent.
- Smaller direct child files are combined into `Misc files` at each parent.
- Every directory's children are sorted from largest to smallest.
- The root starts expanded. Other directories can be expanded and collapsed independently.
- The report can be filtered by a case-insensitive substring of a file or directory name. Matching rows remain fully visible while their retained parent rows are dimmed.
- Dot files and dot directories are included.
- Sizes are displayed only as MB, GB, or TB.

The report is one local HTML file with embedded CSS and a small filtering script. It has no external assets, network requests, or server requirement and can be opened directly with `file://` in a browser.

## Progress

Long scans continuously report:

- elapsed time;
- the directory currently being scanned; and
- allocated space found so far.

Directory, file, and error counters are also displayed. Interactive terminals use an updating Rich display; redirected output receives periodic plain progress records.

## Size semantics and caveats

Space Map uses allocated regular-file bytes (`st_blocks * 512`) and falls back to logical file size when allocated size is unavailable. This avoids overstating sparse files. Binary scaling is used (`1 MB = 1024² bytes`), while labels intentionally remain the familiar MB/GB/TB.

- Directory metadata blocks are excluded.
- Symlinks are not followed.
- Sockets, devices, FIFOs, and other special entries are ignored.
- Hard-linked files are counted once; the first path encountered owns the bytes.
- Directory aliases are traversed once, keyed by filesystem device and inode. This avoids double-counting macOS firmlink views such as `/Users` and `/System/Volumes/Data/Users`; the first path encountered owns the subtree.
- Mounted filesystems are traversed unless `--one-file-system` is supplied.
- On macOS, external Time Machine destinations are skipped by default. APFS destinations are identified by their `Backup` volume role, and legacy HFS+ destinations by `Backups.backupdb`. Use `--include-time-machine` to scan them.
- APFS clones, compression, snapshots, purgeable space, deleted-open files, and filesystem-specific sharing cannot be reconciled perfectly from normal file stats.
- Permission and transient I/O errors do not stop the scan. The resulting report is marked **Partial scan**, and its total should be treated as a lower bound. The error panel starts collapsed and expands into a tree of affected paths.

The utility never deletes, moves, or modifies scanned files. If the output report already exists inside the scanned root, that destination is excluded so the report does not count itself.

## Development

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The implementation and acceptance plan is in [PLAN.md](PLAN.md).
