import plistlib
from pathlib import Path
from types import SimpleNamespace

import space_map.volumes as volumes


def _plist(value: object) -> bytes:
    return plistlib.dumps(value)


def test_external_apfs_backup_role_is_a_time_machine_volume(tmp_path: Path, monkeypatch) -> None:
    info = {
        "Internal": False,
        "DeviceIdentifier": "disk8s2",
        "APFSContainerReference": "disk8",
    }
    apfs = {
        "Containers": [
            {
                "Volumes": [
                    {"DeviceIdentifier": "disk8s1", "Roles": []},
                    {"DeviceIdentifier": "disk8s2", "Roles": ["Backup"]},
                ]
            }
        ]
    }

    def run(command, **kwargs):
        payload = info if command[1] == "info" else apfs
        return SimpleNamespace(stdout=_plist(payload))

    monkeypatch.setattr(volumes.sys, "platform", "darwin")
    monkeypatch.setattr(volumes.subprocess, "run", run)

    assert volumes.is_external_time_machine_volume(tmp_path) is True


def test_internal_apfs_backup_volume_is_not_treated_as_external(
    tmp_path: Path, monkeypatch
) -> None:
    def run(command, **kwargs):
        return SimpleNamespace(
            stdout=_plist(
                {
                    "Internal": True,
                    "DeviceIdentifier": "disk8s2",
                    "APFSContainerReference": "disk8",
                }
            )
        )

    monkeypatch.setattr(volumes.sys, "platform", "darwin")
    monkeypatch.setattr(volumes.subprocess, "run", run)

    assert volumes.is_external_time_machine_volume(tmp_path) is False


def test_external_legacy_hfs_time_machine_destination_is_detected(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "Backups.backupdb").mkdir()

    def run(command, **kwargs):
        return SimpleNamespace(stdout=_plist({"RemovableMediaOrExternalDevice": True}))

    monkeypatch.setattr(volumes.sys, "platform", "darwin")
    monkeypatch.setattr(volumes.subprocess, "run", run)

    assert volumes.is_external_time_machine_volume(tmp_path) is True
