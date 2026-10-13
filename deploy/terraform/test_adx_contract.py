#!/usr/bin/env python3

"""Cross-provider and SDK environment contracts for guided Agent DX deployments."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT.parent / "scripts"


class AdxTerraformContractTest(unittest.TestCase):
    def test_each_provider_exposes_adx_control_and_data_directly(self) -> None:
        for provider in ("aliyun", "huaweicloud"):
            with self.subTest(provider=provider):
                values = (ROOT / provider / "values-akernel.yaml.tmpl").read_text()
                self.assertIn("publicService:", values)
                self.assertIn("enabled: ${adx_public_service_enabled}", values)
                self.assertIn("controlPort: ${adx_control_port}", values)
                self.assertIn("dataPort: ${adx_data_port}", values)
                self.assertNotIn("traefik", values.lower())
                main = (ROOT / provider / "main.tf").read_text()
                variables = (ROOT / provider / "variables.tf").read_text()
                self.assertNotIn("traefik", main.lower())
                self.assertNotIn("traefik", variables.lower())

    def test_each_provider_prepares_identity_before_helm(self) -> None:
        for provider in ("aliyun", "huaweicloud"):
            with self.subTest(provider=provider):
                main = (ROOT / provider / "main.tf").read_text()
                self.assertIn('resource "null_resource" "ensure_adx_secret"', main)
                self.assertIn("../../scripts/ensure-adx-secret.sh", main)
                helm = main[main.index('resource "helm_release" "akernel_core"') :]
                self.assertIn("null_resource.ensure_adx_secret", helm)

    def test_each_provider_renders_the_adx_topology(self) -> None:
        for provider in ("aliyun", "huaweicloud"):
            with self.subTest(provider=provider):
                values = (ROOT / provider / "values-akernel.yaml.tmpl").read_text()
                self.assertIn("adx:", values)
                self.assertIn("  coordinator:\n    replicas: 1", values)
                self.assertIn("  ingressApi:\n    replicas: 1", values)
                self.assertIn('repository: "${master_image_repository}"', values)
                self.assertIn('tag: "${master_image_tag}"', values)
                self.assertIn(
                    'schedulePlacementPolicy: "${schedule_placement_policy}"', values
                )
                self.assertIn("existingSecret: akernel-adx-tls", values)
                self.assertIn("mode: managed", values)
                self.assertIn("appendfsync: everysec", values)
                self.assertIn("replicas: 1", values)


class SdkEnvironmentMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.scripts = root / "deploy/scripts"
        self.scripts.mkdir(parents=True)
        for name in ("common.sh", "print-sdk-env.sh"):
            shutil.copy2(SCRIPTS / name, self.scripts / name)
        key_helper = self.scripts / "get-adx-admin-key.sh"
        key_helper.write_text("#!/usr/bin/env bash\nprintf '%s\\n' adx-test-key\n")
        key_helper.chmod(0o755)
        (root / "deploy/terraform/aliyun").mkdir(parents=True)
        self.profile = root / ".akernel/test"
        self.profile.mkdir(parents=True)
        (self.profile / "config.env").write_text("CORE_NAMESPACE=test-ns\n")
        kubeconfig = self.profile / "kubeconfig"
        kubeconfig.write_text("apiVersion: v1\n")

        binaries = root / "bin"
        binaries.mkdir()
        terraform = binaries / "terraform"
        terraform.write_text(
            """#!/usr/bin/env bash
case "$*" in
  *kubeconfig_path) printf '%s\\n' "${FAKE_KUBECONFIG}" ;;
  *core_namespace) printf '%s\\n' test-ns ;;
  *monitor_namespace) printf '%s\\n' monitor ;;
  *) exit 2 ;;
esac
"""
        )
        kubectl = binaries / "kubectl"
        kubectl.write_text(
            """#!/usr/bin/env bash
case "$*" in
  *"get svc akernel-adx-public"*loadBalancer*) printf '%s' "$FAKE_HOST" ;;
  *"get svc akernel-adx-public"*'name=="control"'*) printf '%s' "$CONTROL" ;;
  *"get svc akernel-adx-public"*'name=="data"'*) printf '%s' "$DATA" ;;
  *"get svc grafana"*) exit 0 ;;
  *) exit 3 ;;
esac
"""
        )
        terraform.chmod(0o755)
        kubectl.chmod(0o755)
        self.environment = dict(
            os.environ,
            PATH=f"{binaries}:{os.environ['PATH']}",
            FAKE_KUBECONFIG=str(kubeconfig),
        )

    def test_generated_sdk_environment_replaces_retired_endpoints(self) -> None:
        sdk_addresses = SCRIPTS.parents[1] / "sdk/python/akernel_sdk/_addresses.py"
        probe = (
            "import json,runpy,sys; sdk=runpy.run_path(sys.argv[1]); "
            "print(json.dumps([(e.scheme,e.host,e.port) for e in "
            "(sdk['api_endpoint_from_env'](),sdk['gateway_endpoint_from_env']())]))"
        )
        for host, control, data, inherited in (
            ("192.0.2.7", 443, 80, "gateway"),
            ("adx.example.test", 443, 80, "legacy"),
            ("adx.example.test", 443, 80, "both"),
            ("adx.example.test", 9443, 80, "gateway"),
            ("adx.example.test", 443, 9080, "gateway"),
            ("2001:db8::7", 443, 80, "both"),
            ("2001:db8::7", 9443, 9080, "both"),
        ):
            with self.subTest(
                host=host, control=control, data=data, inherited=inherited
            ):
                environment = dict(
                    self.environment,
                    FAKE_HOST=host,
                    CONTROL=str(control),
                    DATA=str(data),
                    AKERNEL_SERVER_ADDRESS="retired.example.test",
                    AKERNEL_GATEWAY_ADDRESS=(
                        "" if inherited == "legacy" else "http://retired.example.test"
                    ),
                    YR_GATEWAY_ADDRESS=(
                        ""
                        if inherited == "gateway"
                        else "http://retired-legacy.example.test"
                    ),
                )
                subprocess.run(
                    [
                        self.scripts / "print-sdk-env.sh",
                        "--vendor",
                        "aliyun",
                        "--env",
                        "test",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                sdk_env = self.profile / "sdk.env"
                result = subprocess.check_output(
                    [
                        "bash",
                        "-c",
                        'source "$1"; "$2" -B -c "$3" "$4"',
                        "_",
                        str(sdk_env),
                        sys.executable,
                        probe,
                        str(sdk_addresses),
                    ],
                    text=True,
                    env=environment,
                )
                self.assertEqual(
                    json.loads(result), [["https", host, control], ["http", host, data]]
                )
                self.assertEqual(stat.S_IMODE(sdk_env.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
