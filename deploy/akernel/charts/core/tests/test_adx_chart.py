#!/usr/bin/env python3

"""Rendered-contract tests for the default ADX Kubernetes deployment."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parents[1]


def render() -> tuple[list[dict], str]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "akernel",
            str(CHART),
            "--namespace",
            "akernel-system",
            "--set",
            "adx.tls.existingSecret=adx-test-tls",
            "--set",
            "traefik.enabled=true",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item], result.stdout


class AdxChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resources, cls.rendered = render()

    def resource(self, kind: str, name: str) -> dict:
        for resource in self.resources:
            if resource.get("kind") == kind and resource["metadata"]["name"] == name:
                return resource
        self.fail(f"missing {kind}/{name}")

    def test_default_replaces_legacy_control_plane(self) -> None:
        self.resource("StatefulSet", "akernel-adx-redis")
        self.resource("Deployment", "akernel-adx-control")
        self.resource("Service", "akernel-adx-control")
        self.resource("DaemonSet", "akernel-node")
        names = {item["metadata"]["name"] for item in self.resources}
        self.assertNotIn("akernel-master", names)
        self.assertNotIn("akernel-frontend", names)
        self.assertNotIn("akernel-etcd", names)

    def test_control_preserves_master_image_override(self) -> None:
        result = subprocess.run(
            ["helm", "template", "akernel", str(CHART), "--set",
             "master.image.repository=example.test/control,master.image.tag=release"],
            check=True, capture_output=True, text=True,
        )
        resources = [item for item in yaml.safe_load_all(result.stdout) if item]
        control = next(item for item in resources
                       if item["kind"] == "Deployment"
                       and item["metadata"]["name"] == "akernel-adx-control")
        image = control["spec"]["template"]["spec"]["containers"][0]["image"]
        self.assertEqual(image, "example.test/control:release")

    def test_retired_templates_are_removed(self) -> None:
        for directory in ("etcd", "frontend", "master"):
            self.assertFalse((CHART / "templates" / directory).exists())
        self.assertNotIn("ETCD_ADDRESS", self.rendered)
        self.assertNotIn("YR_IMAGE_PROCESS_CONFIG", self.rendered)
        static = self.resource("ConfigMap", "traefik-static")["data"]["traefik.yml"]
        self.assertIn("file:", static)

    def test_internal_rpc_uses_network_identity_without_node_certificates(self) -> None:
        config = self.resource("ConfigMap", "akernel-adx-config")["data"]
        self.assertNotIn("node-pool:", config["control.yaml"])
        self.assertIn("mode: network", config["control.yaml"])
        self.assertIn("internal_security: network", config["control.yaml"])
        self.assertIn("mode: network", config["node.yaml"])
        self.assertNotIn(".der", config["control.yaml"] + config["node.yaml"])
        self.assertIn("node_id: ${NODE_NAME}", config["node.yaml"])
        self.assertIn("advertised_address: ${INSTANCE_IP}:19001", config["node.yaml"])
        daemonset = self.resource("DaemonSet", "akernel-node")
        container = daemonset["spec"]["template"]["spec"]["containers"][0]
        env = {item["name"]: item.get("value") for item in container["env"]}
        self.assertNotIn("AKERNEL_CONTROL_PLANE", env)
        self.assertEqual(env["AKERNEL_ADX_CONFIG"], "/etc/akernel/adx-node.yaml")

        volumes = {
            item["name"]: item
            for item in daemonset["spec"]["template"]["spec"]["volumes"]
        }
        self.assertNotIn("adx-credentials", volumes)
        control = self.resource("Deployment", "akernel-adx-control")
        volumes = control["spec"]["template"]["spec"]["volumes"]
        secret = next(v["secret"] for v in volumes if v["name"] == "credentials")
        self.assertEqual({i["key"] for i in secret["items"]}, {"public.pem", "public.key", "admin-key"})

    def test_gateway_keeps_control_and_data_ports_separate(self) -> None:
        dynamic = self.resource("ConfigMap", "traefik-dynamic")["data"]["config.yml"]
        self.assertIn('url: "https://akernel-adx-control:8443"', dynamic)
        self.assertIn('url: "http://akernel-adx-control:8080"', dynamic)
        self.assertIn("- websecure", dynamic)
        self.assertIn("- web", dynamic)
        self.assertNotIn("akernel-frontend:8888", dynamic)

        service = self.resource("Service", "akernel-adx-control")
        ports = {port["name"]: port["port"] for port in service["spec"]["ports"]}
        self.assertEqual(ports["edge-control"], 8443)
        self.assertEqual(ports["edge-data"], 8080)

    def test_adx_keeps_both_ports_when_legacy_single_entry_is_disabled(self) -> None:
        result = subprocess.run(
            [
                "helm",
                "template",
                "akernel",
                str(CHART),
                "--namespace",
                "akernel-system",
                "--set",
                "adx.tls.existingSecret=adx-test-tls",
                "--set",
                "traefik.enabled=true",
                "--set",
                "traefik.enableWebEntrypoint=false",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        resources = [item for item in yaml.safe_load_all(result.stdout) if item]
        traefik = next(
            item
            for item in resources
            if item["kind"] == "Service" and item["metadata"]["name"] == "traefik"
        )
        ports = {port["name"] for port in traefik["spec"]["ports"]}
        self.assertIn("websecure", ports)
        self.assertIn("web", ports)

    def test_redis_is_single_member_aof_with_persistent_storage(self) -> None:
        redis = self.resource("StatefulSet", "akernel-adx-redis")
        self.assertEqual(redis["spec"]["replicas"], 1)
        container = redis["spec"]["template"]["spec"]["containers"][0]
        self.assertIn("--appendonly", container["args"])
        self.assertIn("everysec", container["args"])
        claims = redis["spec"]["volumeClaimTemplates"]
        self.assertEqual(claims[0]["metadata"]["name"], "data")

    def test_external_redis_uses_a_secret_and_omits_managed_redis(self) -> None:
        result = subprocess.run(
            [
                "helm",
                "template",
                "akernel",
                str(CHART),
                "--namespace",
                "akernel-system",
                "--set",
                "adx.redis.mode=external",
                "--set",
                "adx.redis.external.existingSecret=external-redis",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        resources = [item for item in yaml.safe_load_all(result.stdout) if item]
        names = {item["metadata"]["name"] for item in resources}
        self.assertNotIn("akernel-adx-redis", names)
        control = next(
            item
            for item in resources
            if item["kind"] == "Deployment"
            and item["metadata"]["name"] == "akernel-adx-control"
        )
        node = next(item for item in resources if item["kind"] == "DaemonSet")
        for workload in (control, node):
            environment = workload["spec"]["template"]["spec"]["containers"][0]["env"]
            redis = next(
                item for item in environment if item["name"] == "ADX_REDIS_URL"
            )
            self.assertEqual(
                redis["valueFrom"]["secretKeyRef"],
                {"name": "external-redis", "key": "redis-url"},
            )

    def test_external_redis_requires_a_secret(self) -> None:
        result = subprocess.run(
            [
                "helm",
                "template",
                "akernel",
                str(CHART),
                "--set",
                "adx.redis.mode=external",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("adx.redis.external.existingSecret is required", result.stderr)

    def test_adx_mode_does_not_render_unused_legacy_control_secrets(self) -> None:
        names = {item["metadata"]["name"] for item in self.resources}
        self.assertNotIn("akernel-component-tls", names)
        self.assertNotIn("akernel-master-secret", names)

    def test_multiple_control_replicas_are_rejected(self) -> None:
        result = subprocess.run(
            [
                "helm",
                "template",
                "akernel",
                str(CHART),
                "--set",
                "adx.control.replicas=2",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("adx.control.replicas must be 1", result.stderr)


if __name__ == "__main__":
    unittest.main()
