#!/usr/bin/env python3
"""AFS mount readiness and shared checkpoint profile regression tests."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOST = load("afs_host", ROOT / "deploy/standalone/validate-afs.py")
CONFIG = load("afs_config", ROOT / "builder/scripts/prepare-adx-config.py")


class AfsConfigTest(unittest.TestCase):
    def test_host_requires_an_actual_writable_dfs_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            for output, valid in (("afs-dfs fuse rw,nosuid\n", True),
                                  ("/dev/root ext4 rw\n", False),
                                  ("afs-ownerfs fuse rw\n", False),
                                  ("afs-dfs fuse ro\n", False)):
                with self.subTest(output=output), patch.object(HOST.subprocess, "run") as run:
                    run.return_value.stdout = output
                    if valid:
                        self.assertEqual(HOST.validate(directory, "acceptance/checkpoints"), str(Path(directory).resolve()))
                    else:
                        with self.assertRaises(ValueError):
                            HOST.validate(directory, "acceptance/checkpoints")
            with patch.object(HOST.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "findmnt")):
                with self.assertRaises(subprocess.CalledProcessError):
                    HOST.validate(directory, "acceptance/checkpoints")

    def test_invalid_prefix_is_rejected_before_mount_query(self):
        with tempfile.TemporaryDirectory() as directory:
            for prefix in ("../data", "/data", "data//checkpoints", "data;exit"):
                with self.subTest(prefix=prefix), patch.object(HOST.subprocess, "run") as run:
                    with self.assertRaises(ValueError):
                        HOST.validate(directory, prefix)
                    run.assert_not_called()

    def test_profile_shares_checkpoint_store_and_preserves_local_runtime_paths(self):
        for pvm in (False, True):
            with self.subTest(pvm=pvm), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "afs.yaml"
                source = ROOT / "builder/config/adx-standalone.yaml"
                original = yaml.safe_load(source.read_text())
                with patch.object(CONFIG.subprocess, "run") as run:
                    run.return_value.stdout = "afs-dfs fuse rw\n"
                    CONFIG.configure(source, target, Path("/mnt/akernel-shared"), "test/checkpoints", pvm=pvm)
                profile = yaml.safe_load(target.read_text())
                overrides = profile["service_overrides"]
                storage = overrides["adxlet"]["config"]["checkpoint_storage"]
                self.assertEqual(storage, overrides["coordinator"]["config"]["checkpoint_reclaimers"][0])
                self.assertEqual(storage["kind"], "distributed_fs")
                self.assertIsNone(overrides["adxlet"]["config"]["checkpoint_dir"])
                self.assertEqual(profile["runtime_profile"], original["runtime_profile"])
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_pvm_only_changes_rpc_budgets_and_supports_in_place_generation(self):
        source = ROOT / "builder/config/adx-standalone.yaml"
        original = yaml.safe_load(source.read_text())
        for pvm in (False, True):
            with self.subTest(pvm=pvm), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "profile.yaml"
                target.write_text(source.read_text())
                with patch.dict(os.environ, {"ENABLE_TRACE": "false"}):
                    CONFIG.configure(target, target, None, "unused", pvm=pvm)
                result = yaml.safe_load(target.read_text())
                overrides = result["service_overrides"]
                self.assertEqual(overrides["coordinator"]["config"]["autoscaling_listen"], "127.0.0.1:19092")
                self.assertEqual(overrides["apiserver"]["config"]["metrics_listen"], "127.0.0.1:19093")
                if pvm:
                    for role in ("coordinator", "adxlet"):
                        self.assertEqual(overrides[role]["config"].pop("rpc_timeout_seconds"), 90)
                self.assertEqual(result, original)

    def test_standalone_trace_flag_configures_processes_and_guest_without_afs(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"ENABLE_TRACE": "true"}):
            target = Path(directory) / "trace.yaml"
            with patch.object(CONFIG.subprocess, "run") as run:
                CONFIG.configure(ROOT / "builder/config/adx-standalone.yaml", target, None, "unused")
                run.assert_not_called()
            overrides = yaml.safe_load(target.read_text())["service_overrides"]
            for role in ("coordinator", "apiserver", "adxlet", "ingress"):
                self.assertEqual(overrides[role]["env"]["ADX_TRACE_ENABLED"], "true")
                self.assertEqual(overrides[role]["env"]["ADX_TRACE_SAMPLE_RATIO"], "0.1")
            node = overrides["adxlet"]["config"]
            self.assertEqual(node["execd_env"]["OTEL_EXPORTER_OTLP_ENDPOINT"], "http://10.88.0.1:4318")
            self.assertEqual(node["execd_env"]["ADX_EXECD_CONTROL_SOCKET_PATH"], "/run/akernel")
            self.assertNotIn("checkpoint_storage", node)

    def test_container_rechecks_mount_before_enabling_shared_storage(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(CONFIG.subprocess, "run") as run:
            run.return_value.stdout = "/dev/root ext4 rw\n"
            target = Path(directory) / "afs.yaml"
            with self.assertRaises(ValueError):
                CONFIG.configure(ROOT / "builder/config/adx-standalone.yaml", target,
                                 Path("/mnt/akernel-shared"), "test/checkpoints")
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
