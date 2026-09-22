#!/usr/bin/env python3
"""Verify the pinned ADX base package before AKernel consumes it."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO


def _sha256(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def verify(archive: Path, lock_path: Path) -> None:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("schema_version") != 1:
        raise ValueError("unsupported ADX release lock schema")
    source = lock.get("source") or {}
    expected_commit = source.get("commit")
    expected_archive = lock.get("archive") or {}
    if archive.stat().st_size != expected_archive.get("size"):
        raise ValueError("ADX release archive size does not match the lock")
    with archive.open("rb") as stream:
        if _sha256(stream) != expected_archive.get("sha256"):
            raise ValueError("ADX release archive digest does not match the lock")

    expected_files = (lock.get("package") or {}).get("files")
    if not isinstance(expected_files, dict) or not expected_files:
        raise ValueError("ADX release lock has no consumed files")
    for name in expected_files:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"invalid consumed file path in lock: {name}")

    with tarfile.open(archive, "r:gz") as package:
        members = {}
        for member in package.getmembers():
            normalized = member.name.removeprefix("./")
            path = PurePosixPath(normalized)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe path in ADX release: {member.name}")
            if normalized in members:
                raise ValueError(f"duplicate path in ADX release: {normalized}")
            members[normalized] = member
        manifest_member = members.get("manifest.json")
        if manifest_member is None or not manifest_member.isfile():
            raise ValueError("ADX release manifest is missing")
        manifest_stream = package.extractfile(manifest_member)
        if manifest_stream is None:
            raise ValueError("ADX release manifest cannot be read")
        manifest = json.load(manifest_stream)
        package_info = lock.get("package") or {}
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported ADX package manifest schema")
        if manifest.get("commit") != expected_commit or manifest.get("dirty"):
            raise ValueError("ADX release source identity does not match the lock")
        if manifest.get("target") != package_info.get("target"):
            raise ValueError("ADX release target does not match the lock")
        if manifest.get("profile") != package_info.get("profile"):
            raise ValueError("ADX release profile does not match the lock")

        manifest_files = manifest.get("files") or {}
        for name, expected_digest in expected_files.items():
            if manifest_files.get(name) != expected_digest:
                raise ValueError(f"ADX manifest digest mismatch: {name}")
            member = members.get(name)
            if member is None or not member.isfile() or member.issym():
                raise ValueError(f"ADX consumed file is missing: {name}")
            stream = package.extractfile(member)
            if stream is None or _sha256(stream) != expected_digest:
                raise ValueError(f"ADX consumed file digest mismatch: {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "adx-release.lock.json",
    )
    args = parser.parse_args()
    verify(args.archive, args.lock)
    print("ADX release verified")


if __name__ == "__main__":
    main()
