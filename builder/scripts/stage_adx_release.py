#!/usr/bin/env python3
"""Verify and stage the exact ADX release files consumed by AKernel."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from verify_adx_release import verify


def stage(archive: Path, destination: Path, lock_path: Path) -> None:
    """Verify ``archive`` and atomically stage only lock-listed files."""

    verify(archive, lock_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    expected_files = lock["package"]["files"]
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(f"ADX stage destination already exists: {destination}")

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    try:
        with tarfile.open(archive, "r:gz") as package:
            members = {
                member.name.removeprefix("./"): member
                for member in package.getmembers()
            }
            for name in expected_files:
                member = members[name]
                source = package.extractfile(member)
                if source is None:
                    raise ValueError(f"ADX consumed file cannot be read: {name}")
                target = temporary / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                os.chmod(target, member.mode & 0o777)
        temporary.rename(destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "adx-release.lock.json",
    )
    args = parser.parse_args()
    stage(args.archive, args.destination, args.lock)
    print(f"ADX release staged at {args.destination}")


if __name__ == "__main__":
    main()
