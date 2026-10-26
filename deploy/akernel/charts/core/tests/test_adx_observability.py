#!/usr/bin/env python3
"""Collection contracts for local node telemetry and isolated ADX roles."""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[5]
CHART = ROOT / "deploy/akernel/charts/core"


class ObservabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        result = subprocess.run(
            ["helm", "template", "akernel", str(CHART), "-n", "akernel",
             "--set", "monitoring.prometheusEndpoint=prometheus.akernel-monitor:9090",
             "--set", "monitoring.lokiEndpoint=loki.akernel-monitor:3100",
             "--set", "monitoring.tempoEndpoint=tempo.akernel-monitor:4317"],
            check=True, capture_output=True, text=True,
        )
        cls.resources = {
            (r["kind"], r["metadata"]["name"]): r
            for r in yaml.safe_load_all(result.stdout) if r
        }

    def test_node_scrapes_only_local_adx_targets(self) -> None:
        config = yaml.safe_load((CHART / "files/otel-collector/config.yaml").read_text())
        jobs = config["receivers"]["prometheus/adx"]["config"]["scrape_configs"]
        targets = {j["job_name"]: j["static_configs"][0]["targets"] for j in jobs}
        self.assertEqual(targets, {"adxlet": ["127.0.0.1:19091"],
                                   "adx-relay": ["127.0.0.1:18443"],
                                   "otel-collector": ["127.0.0.1:18889"]})
        self.assertIn("prometheus/adx", config["service"]["pipelines"]["metrics"]["receivers"])
        self.assertEqual((ROOT / "builder/config/otel-collector-config.yaml").read_bytes(),
                         (CHART / "files/otel-collector/config.yaml").read_bytes())

    def test_standalone_collects_all_local_control_and_data_metrics(self) -> None:
        config = yaml.safe_load((ROOT / "builder/config/otel-collector-standalone.yaml").read_text())
        jobs = config["receivers"]["prometheus/adx"]["config"]["scrape_configs"]
        targets = {job["job_name"]: job["static_configs"][0]["targets"] for job in jobs}
        self.assertEqual(targets, {
            "adxlet": ["127.0.0.1:19091"], "adx-relay": ["127.0.0.1:18443"],
            "adx-coordinator": ["127.0.0.1:19090"], "adx-apiserver": ["127.0.0.1:19093"],
            "adx-ingress": ["127.0.0.1:18080"], "otel-collector": ["127.0.0.1:18889"],
        })

    def test_adxlet_samples_the_sandboxd_resource_socket_for_both_clouds(self) -> None:
        configs = self.resources[("ConfigMap", "akernel-adx-config")]["data"]
        node = yaml.safe_load(configs["node.yaml"])
        adxlet = next(s for s in node["services"] if s["role"] == "adxlet")
        source = adxlet["config"]["resource_source"]
        self.assertEqual(source["kind"], "sandboxd")
        self.assertGreater(source["valid_for_seconds"], 0)
        self.assertNotIn("disk_path", source)
        sandboxd_configs = {
            "default": next(r["data"]["sandboxd_config.toml"]
                            for r in self.resources.values()
                            if "sandboxd_config.toml" in r.get("data", {})),
            **{provider: (ROOT / "deploy/terraform" / provider /
                          "values-akernel.yaml.tmpl").read_text()
               for provider in ("aliyun", "huaweicloud")},
        }
        for provider, config in sandboxd_configs.items():
            with self.subTest(provider=provider):
                section = config.split("[plugin.node_resource]", 1)[1]
                socket = re.search(r'^\s*sock_path\s*=\s*"([^"]+)"', section, re.MULTILINE)
                self.assertIsNotNone(socket)
                self.assertEqual(source["socket"], socket.group(1))

    def test_node_logs_include_runtime_and_structured_adx_records(self) -> None:
        config = yaml.safe_load((CHART / "files/otel-collector/config.yaml").read_text())
        receivers = config["receivers"]
        self.assertIn("filelog/runtime", config["service"]["pipelines"]["logs"]["receivers"])
        self.assertTrue(any(op["type"] == "json_parser" for op in receivers["filelog/adx"]["operators"]))
        attrs = config["processors"]["resource"]["attributes"]
        self.assertTrue(any(a["key"] == "adx_env" for a in attrs))

    def test_no_metrics_service_or_standalone_collector_deployment(self) -> None:
        names = [name for kind, name in self.resources if kind in ("Service", "Deployment")]
        self.assertFalse(any("metrics" in name or "collector" in name for name in names))
        node = self.resources[("DaemonSet", "akernel-node")]["spec"]["template"]["spec"]
        self.assertEqual([c["name"] for c in node["containers"]], ["akernel-node"])

    def test_control_roles_collect_locally_without_exposing_metrics_ports(self) -> None:
        for role in ("coordinator", "ingress-api"):
            spec = self.resources[("Deployment", f"akernel-adx-{role}")]["spec"]["template"]["spec"]
            collector = next(c for c in spec["containers"] if c["name"] == "otel-collector")
            self.assertEqual(collector["command"], ["/usr/local/bin/otelcol-contrib"])
            env = {e["name"]: e for e in collector["env"]}
            self.assertIn("POD_NAME", env)
            self.assertIn("NODE_NAME", env)
            mounts = {m["name"]: m for m in collector["volumeMounts"]}
            self.assertTrue(mounts["adx-logs"]["readOnly"])

    def test_deployment_keeps_native_metrics_and_trace_at_local_collector(self) -> None:
        data = self.resources[("ConfigMap", "akernel-adx-config")]["data"]
        for role in ("coordinator", "ingress-api", "node"):
            cfg = yaml.safe_load(data[f"{role}.yaml"])
            self.assertTrue(cfg["logging"]["line_records"])
            for service in cfg["services"]:
                self.assertEqual(service["env"]["ADX_LOG_FORMAT"], "json")
                self.assertEqual(service["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"], "http://127.0.0.1:4318")

    def test_control_collector_does_not_bind_the_apiserver_port(self) -> None:
        config = yaml.safe_load((CHART / "files/otel-collector/control.yaml").read_text())
        prometheus = config["service"]["telemetry"]["metrics"]["readers"][0]["pull"]["exporter"]["prometheus"]
        self.assertEqual(prometheus["host"], "127.0.0.1")
        self.assertNotEqual(prometheus["port"], 18888)

    def test_loki_indexes_dashboard_environment_and_component(self) -> None:
        config = yaml.safe_load((ROOT / "deploy/akernel/charts/monitor/files/loki/local-config.yaml").read_text())
        indexed = config["limits_config"]["otlp_config"]["resource_attributes"]["attributes_config"][0]["attributes"]
        self.assertIn("adx_env", indexed)
        self.assertIn("component_name", indexed)

    def test_custom_prometheus_claim_and_running_count_rule(self) -> None:
        result = subprocess.run(
            ["helm", "template", "akernel-monitor", str(ROOT / "deploy/akernel/charts/monitor"),
             "-n", "akernel-monitor", "--set", "prometheusServer.persistence.claimName=existing-data"],
            check=True, capture_output=True, text=True,
        )
        resources = {(r["kind"], r["metadata"]["name"]): r
                     for r in yaml.safe_load_all(result.stdout) if r}
        self.assertIn(("PersistentVolumeClaim", "existing-data"), resources)
        volumes = resources[("StatefulSet", "prometheus")]["spec"]["template"]["spec"]["volumes"]
        self.assertEqual(next(v for v in volumes if v["name"] == "prometheus-storage")["persistentVolumeClaim"]["claimName"], "existing-data")
        cm = resources[("ConfigMap", "prometheus-config")]["data"]
        self.assertIn("/etc/prometheus/adx-rules.yaml", cm["prometheus.yml"])
        rules = yaml.safe_load(cm["adx-rules.yaml"])["groups"][0]["rules"]
        self.assertEqual(rules[0]["record"], "sandbox_running")
        self.assertIn('state="Running"', rules[0]["expr"])

    def test_primary_collectors_exclude_instance_resource_samples(self) -> None:
        paths = [ROOT / "builder/config/otel-collector-config.yaml",
                 ROOT / "builder/config/otel-collector-standalone.yaml",
                 *(CHART / f"files/otel-collector/{role}.yaml"
                   for role in ("config", "control", "ingress-api"))]
        for path in paths:
            with self.subTest(path=path):
                config = yaml.safe_load(path.read_text())
                pipeline = config["service"]["pipelines"]["metrics"]
                self.assertIn("filter/summary_metrics", pipeline["processors"])
                conditions = config["processors"]["filter/summary_metrics"]["metrics"]["datapoint"]
                for identity in ("environment_id", "sandbox_id"):
                    self.assertIn(f'attributes["{identity}"] != nil', conditions)
                    self.assertIn(f'resource.attributes["{identity}"] != nil', conditions)
                for signal in ("logs", "traces"):
                    self.assertNotIn("filter/summary_metrics",
                                     config["service"]["pipelines"][signal]["processors"])

    def test_existing_detail_dashboard_url_uses_short_retention_metrics(self) -> None:
        dashboards = ROOT / "deploy/akernel/charts/monitor/dashboards"
        alias = json.loads((dashboards / "sandbox-lifecycle-dashboard.json").read_text())
        native = json.loads((dashboards / "adx-environments.json").read_text())
        self.assertEqual(alias["uid"], "sandbox-metrics")
        self.assertEqual(alias["panels"], native["panels"])
        self.assertEqual(alias["templating"], native["templating"])

    def test_latest_master_metrics_contract(self) -> None:
        data = self.resources[("ConfigMap", "akernel-adx-config")]["data"]
        api = yaml.safe_load(data["ingress-api.yaml"])["services"][0]
        self.assertEqual(api["config"]["metrics_listen"], "127.0.0.1:19093")
        node = yaml.safe_load(data["node.yaml"])["services"][0]
        self.assertEqual(node["config"]["metrics_interval_seconds"], 15)
        config = yaml.safe_load(self.resources[("ConfigMap", "akernel-otel-collector-config")]["data"]["ingress-api.yaml"])
        jobs = config["receivers"]["prometheus/adx"]["config"]["scrape_configs"]
        self.assertTrue(any(j["job_name"] == "adx-apiserver" for j in jobs))
        self.assertTrue(any(j["job_name"] == "otel-collector" for j in jobs))

    def test_metric_sampling_rejects_disabled_or_invalid_intervals(self) -> None:
        for interval in ("0", "-1", "1.5", "bad", "3601"):
            with self.subTest(interval=interval):
                result = subprocess.run(
                    ["helm", "template", "akernel", str(CHART), "--set-string",
                     f"adx.node.metricsIntervalSeconds={interval}"],
                    capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("metricsIntervalSeconds must be an integer", result.stderr)

    def test_optional_environment_details_have_separate_storage(self) -> None:
        result = subprocess.run(
            ["helm", "template", "monitor", str(ROOT / "deploy/akernel/charts/monitor"),
             "--set", "environmentDetails.enabled=true"],
            check=True, capture_output=True, text=True,
        )
        resources = {(r["kind"], r["metadata"]["name"]): r
                     for r in yaml.safe_load_all(result.stdout) if r}
        details = resources[("StatefulSet", "prometheus-details")]
        container = details["spec"]["template"]["spec"]["containers"][0]
        self.assertIn("--storage.tsdb.retention.time=24h", container["args"])
        config = yaml.safe_load(resources[("ConfigMap", "prometheus-details")]["data"]["prometheus.yml"])
        self.assertTrue(all(j["metrics_path"] == "/metrics/environments" for j in config["scrape_configs"]))
        self.assertIn("prometheus-details", resources[("ConfigMap", "grafana-datasources")]["data"]["prometheus.yaml"])
        rules = yaml.safe_load(resources[("ConfigMap", "prometheus-config")]["data"]["adx-rules.yaml"])
        records = {r["record"] for g in rules["groups"] for r in g["rules"]}
        self.assertIn("adx:environment_create_request_qps:rate1m", records)

    def test_dashboard_uids_and_environment_contract(self) -> None:
        dashboard_dir = ROOT / "deploy/akernel/charts/monitor/dashboards"
        for name in ("schedule", "data-plane", "process-resources", "environment-logs", "environments"):
            p = dashboard_dir / f"adx-{name}.json"
            dashboard = json.loads(p.read_text())
            self.assertEqual(dashboard["uid"], f"adx-{name}")
            self.assertIn("adx_env", p.read_text())


if __name__ == "__main__":
    unittest.main()
