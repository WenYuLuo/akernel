#!/usr/bin/env python3
"""Contract tests for the RRT-only AKernel runtime package."""

from __future__ import annotations

import unittest
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[2]


class RuntimeContractTest(unittest.TestCase):
    def test_node_service_inherits_deployment_configuration(self) -> None:
        unit = (ROOT / "builder/systemd_services/adx.service").read_text()
        inherited = {
            name
            for line in unit.splitlines()
            if line.startswith("PassEnvironment=")
            for name in line.split("=", 1)[1].split()
        }
        required = {
            "AKERNEL_ADX_CONFIG",
            "AKERNEL_ADX_MANAGED_CREDENTIALS",
            "AKERNEL_ADX_STATE_DIR",
            "ADX_REDIS_URL",
            "NODE_NAME",
            "INSTANCE_IP",
        }
        self.assertFalse(required - inherited, required - inherited)

    def test_sdk_metadata_has_no_actor_runtime_dependency(self) -> None:
        metadata = tomllib.loads(
            (ROOT / "sdk/python/pyproject.toml").read_text(encoding="utf-8")
        )
        requirements = list(metadata["project"]["dependencies"])
        for values in metadata["project"]["optional-dependencies"].values():
            requirements.extend(values)
        normalized = {item.split("=", 1)[0].lower() for item in requirements}
        self.assertNotIn("openyuanrong-sdk", normalized)

    def test_actor_backend_sources_are_absent(self) -> None:
        backend = ROOT / "sdk/python/akernel_sdk/_backends"
        self.assertFalse(list(backend.glob("openyuanrong_sdk*.py")))

    def test_image_does_not_install_retired_control_plane(self) -> None:
        dockerfile = (ROOT / "builder/node.Dockerfile").read_text()
        self.assertNotIn("OPEN_YR", dockerfile)
        self.assertNotIn("yuanrong.service", dockerfile)
        self.assertFalse((ROOT / "builder/systemd_services/yuanrong.service").exists())

    def test_default_sdk_config_keeps_the_existing_address_contract(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertNotIn("export AKERNEL_GATEWAY_ADDRESS=", workflow)

    def test_actor_runtime_entrypoint_is_absent(self) -> None:
        self.assertFalse((ROOT / "builder/scripts/entryfile.sh").exists())

    def test_image_build_exposes_only_the_rrt_profile(self) -> None:
        runtime = (ROOT / "builder/runtime.Dockerfile").read_text(encoding="utf-8")
        build = (ROOT / "deploy/scripts/build-image.sh").read_text(encoding="utf-8")
        self.assertNotIn("openyuanrong_sdk", runtime)
        self.assertNotIn("runtime-python", runtime)
        self.assertIn("--target runtime-rrt", build)
        self.assertNotIn("--runtime-profile", build)


if __name__ == "__main__":
    unittest.main()
