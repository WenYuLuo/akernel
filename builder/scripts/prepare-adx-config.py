#!/usr/bin/env python3
"""Apply PVM, telemetry and mounted checkpoint options to the standalone profile."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import subprocess

import yaml


def configure(
    source: Path, destination: Path, mount: Path | None, prefix: str, *, pvm: bool = False,
) -> None:
    cfg = yaml.safe_load(source.read_text())
    overrides = cfg.setdefault("service_overrides", {})
    node = overrides.setdefault("adxlet", {}).setdefault("config", {})
    if pvm:
        # Nested PVM cleanup needs a longer RPC budget; guest boot stays unchanged.
        for role in ("coordinator", "adxlet"):
            overrides.setdefault(role, {}).setdefault("config", {})["rpc_timeout_seconds"] = 90
    if mount is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", prefix):
            raise ValueError("checkpoint prefix must contain safe relative components")
        if str(mount) != "/mnt/akernel-shared":
            raise ValueError("unexpected shared checkpoint mount")
        info = subprocess.run(
            ["findmnt", "-rn", "-M", str(mount), "-o", "SOURCE,FSTYPE,OPTIONS"],
            check=True, text=True, capture_output=True,
        ).stdout.split()
        if (len(info) != 3 or info[0] != "afs-dfs" or not info[1].startswith("fuse")
                or "rw" not in info[2].split(",")):
            raise ValueError("shared checkpoint path must be a writable AFS DFS mount")
        storage = {"kind": "distributed_fs", "alias": "afs-checkpoints",
                   "mount_root": str(mount), "prefix": prefix}
        overrides.setdefault("coordinator", {}).setdefault("config", {})["checkpoint_reclaimers"] = [storage]
        node["checkpoint_storage"] = storage
        node["checkpoint_dir"] = None
    if os.environ.get("ENABLE_TRACE", "false") == "true":
        for role in ("coordinator", "apiserver", "adxlet", "ingress"):
            overrides.setdefault(role, {}).setdefault("env", {}).update({
                "ADX_TRACE_ENABLED": "true", "ADX_TRACE_SAMPLE_RATIO": "0.1",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
            })
        node.setdefault("execd_env", {}).update({
            "ADX_TRACE_ENABLED": "true", "ADX_TRACE_SAMPLE_RATIO": "0.1",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://10.88.0.1:4318",
        })
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(cfg, sort_keys=False))
    destination.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--mount", type=Path, default=None)
    parser.add_argument("--prefix", default="akernel/checkpoints")
    parser.add_argument("--pvm", action="store_true", help="use the PVM cleanup RPC budget")
    args = parser.parse_args()
    configure(args.source, args.destination, args.mount, args.prefix, pvm=args.pvm)


if __name__ == "__main__":
    main()
