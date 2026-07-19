from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

_DISKUTIL = "/usr/sbin/diskutil"


def is_external_time_machine_volume(path: Path) -> bool:
    """Return whether path is a mounted external Time Machine backup volume."""
    if sys.platform != "darwin":
        return False

    try:
        info = _diskutil_plist("info", "-plist", os.fspath(path))
        is_external = (
            info.get("Internal") is False or info.get("RemovableMediaOrExternalDevice") is True
        )
        if not is_external:
            return False

        device_identifier = info.get("DeviceIdentifier")
        container_reference = info.get("APFSContainerReference")
        if isinstance(device_identifier, str) and isinstance(container_reference, str):
            apfs = _diskutil_plist("apfs", "list", "-plist", container_reference)
            if _volume_has_backup_role(apfs, device_identifier):
                return True

        # Time Machine used this directory on HFS+ destinations before APFS
        # backup volume roles were introduced.
        return (path / "Backups.backupdb").is_dir()
    except (OSError, ValueError, plistlib.InvalidFileException, subprocess.SubprocessError):
        # Detection should never turn a readable mounted volume into a scan error.
        return False


def _diskutil_plist(*arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [_DISKUTIL, *arguments],
        check=True,
        capture_output=True,
        timeout=5,
    )
    value = plistlib.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("diskutil did not return a dictionary")
    return value


def _volume_has_backup_role(apfs: dict[str, Any], device_identifier: str) -> bool:
    containers = apfs.get("Containers", ())
    if not isinstance(containers, list):
        return False
    for container in containers:
        if not isinstance(container, dict):
            continue
        volumes = container.get("Volumes", ())
        if not isinstance(volumes, list):
            continue
        for volume in volumes:
            if not isinstance(volume, dict) or volume.get("DeviceIdentifier") != device_identifier:
                continue
            roles = volume.get("Roles", ())
            return isinstance(roles, list) and any(
                isinstance(role, str) and role.casefold() == "backup" for role in roles
            )
    return False
