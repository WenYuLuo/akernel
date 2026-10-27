#!/usr/bin/env python3
"""Check ADX log/trace cluster scope against isolated Loki and Tempo instances."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener

import yaml

ROOT = Path(__file__).resolve().parents[3]
MONITOR = ROOT / "deploy/akernel/charts/monitor"
HTTP = build_opener(ProxyHandler({}))


def request(url: str, value: dict | None = None) -> dict:
    data = None if value is None else json.dumps(value).encode()
    with HTTP.open(Request(url, data=data, headers={"Content-Type": "application/json"}), timeout=10) as reply:
        body = reply.read()
        return json.loads(body) if body else {}


def wait(predicate, seconds: int = 90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except OSError:
            pass
        time.sleep(2)
    raise TimeoutError("signal query did not reach the expected result")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser", action="store_true", help="exercise real Grafana TemplateSrv in headless Chrome")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    owned = {}
    network = False
    checks = []
    result = {"checks": checks, "cleanup_errors": []}
    name = "adx-signal-contract-" + uuid.uuid4().hex[:10]

    def start(role: str, image: str, ports: list[int], config: dict | None,
              options: list[str] | None = None, command_args: list[str] | None = None) -> dict[int, str]:
        path = output / (role + ".yaml")
        if config is not None:
            path.write_text(yaml.safe_dump(config))
        command = ["docker", "run", "-d", "--name", name + "-" + role,
                   "--label", "akernel.task=signal-contract", "--cpus=1", "--memory=512m", "--network", name]
        for port in ports:
            command += ["-p", f"127.0.0.1::{port}"]
        command += options or []
        if config is not None:
            command += ["-v", str(path) + ":/config.yaml:ro"]
        command += [image] + (command_args if command_args is not None else ["-config.file=/config.yaml"])
        identity = subprocess.check_output(command, text=True).strip()
        owned[role] = identity
        metadata = json.loads(subprocess.check_output(["docker", "inspect", identity], text=True))[0]
        bindings = metadata["NetworkSettings"]["Ports"]
        return {port: "http://127.0.0.1:" + bindings[f"{port}/tcp"][0]["HostPort"] for port in ports}

    try:
        subprocess.run(["docker", "network", "create", name], check=True, stdout=subprocess.DEVNULL)
        network = True
        loki = yaml.safe_load((MONITOR / "files/loki/local-config.yaml").read_text())
        tempo = yaml.safe_load((MONITOR / "files/tempo/config.yaml").read_text())
        # The fixture tests search/ingestion; metric generation has its own Prometheus acceptance.
        tempo.pop("metrics_generator", None)
        tempo.pop("overrides", None)
        tempo["storage"]["trace"]["local"]["path"] = "/tmp/tempo/traces"
        tempo["storage"]["trace"]["wal"]["path"] = "/tmp/tempo/wal"
        lp = start("loki", "grafana/loki:3.4.2", [3100], loki)[3100]
        tp = start("tempo", "grafana/tempo:2.7.1", [3200, 4318], tempo)
        wait(lambda: request(lp + "/loki/api/v1/status/buildinfo"))
        wait(lambda: request(tp[3200] + "/api/search?" + urlencode({"q": "{}"})))
        now = time.time_ns()
        trace_ids = {}
        for index, cluster in enumerate(("cluster.a", "clusterxa"), 1):
            attrs = [{"key": key, "value": {"stringValue": value}} for key, value in (
                ("cluster", cluster), ("adx_env", "shared"), ("service.name", "adx-apiserver"),
                ("component_name", "adx-runtime"),
            )]
            request(lp + "/otlp/v1/logs", {"resourceLogs": [{"resource": {"attributes": attrs},
                "scopeLogs": [{"scope": {}, "logRecords": [{"timeUnixNano": str(now),
                    "body": {"stringValue": "cluster-scope-marker " + cluster},
                    "attributes": [{"key": "runtime_id", "value": {"stringValue": "same-runtime"}}]}]}]}]})
            trace_id = f"{index:032x}"
            trace_ids[cluster] = trace_id
            request(tp[4318] + "/v1/traces", {"resourceSpans": [{"resource": {"attributes": attrs},
                "scopeSpans": [{"scope": {}, "spans": [{"traceId": trace_id, "spanId": f"{index:016x}",
                    "name": "GET /api/environment/v1/environments", "kind": 2,
                    "startTimeUnixNano": str(now), "endTimeUnixNano": str(now + 1000000),
                    "attributes": [{"key": "http.route", "value": {"stringValue": "/api/environment/v1/environments"}},
                                   {"key": "http.response.status_code", "value": {"intValue": "200"}}]}]}]}]})
        dashboard = json.loads((MONITOR / "dashboards/adx-environment-logs.json").read_text())
        log_query = next(t["expr"] for p in dashboard["panels"] for t in p.get("targets", []) if "expr" in t)
        trace_query = next(t["query"] for p in dashboard["panels"] for t in p.get("targets", [])
                           if t.get("queryType") == "traceql")
        all_value = next(v["allValue"] for v in dashboard["templating"]["list"] if v["name"] == "cluster")
        for selected, expected in (("cluster.a", {"cluster.a"}), ("clusterxa", {"clusterxa"}),
                                   (all_value, set(trace_ids))):
            regex = selected if selected == all_value else re.escape(selected)
            # Match Grafana's quoted-label regex escaping for Loki.
            expr = (log_query.replace("$cluster", regex.replace("\\", "\\\\"))
                    .replace("$adx_env", "shared").replace("${runtime_id:raw}", "same-runtime")
                    .replace("${log_search:percentencode}", ""))
            url = lp + "/loki/api/v1/query_range?" + urlencode({"query": expr, "start": str(now - 60000000000),
                                                               "end": str(now + 60000000000)})
            wait(lambda: {r["stream"]["cluster"] for r in request(url)["data"]["result"]} == expected)
            checks.append("LogQL scope " + selected)
            query = trace_query.replace("${cluster:raw}", selected).replace("$adx_env", "shared")
            url = tp[3200] + "/api/search?" + urlencode({"q": query, "limit": 20})
            expected_ids = {trace_ids[c] for c in expected}
            wait(lambda: {r["traceID"].zfill(32) for r in request(url).get("traces", [])} == expected_ids)
            checks.append("TraceQL scope " + selected)
            for filename in ("adx-environment-logs.json", "adx-schedule.json"):
                d = json.loads((MONITOR / "dashboards" / filename).read_text())
                link = next(link["url"] for link in d["links"] if "/explore?" in link.get("url", ""))
                link = (link.replace("${cluster:percentencode}", selected if selected == all_value else quote(selected, safe=""))
                        .replace("${adx_env:percentencode}", all_value if selected == all_value else "shared"))
                panes = json.loads(parse_qs(urlparse(link).query)["panes"][0])
                query = next(iter(panes.values()))["queries"][0]["query"]
                url = tp[3200] + "/api/search?" + urlencode({"q": query, "limit": 20})
                wait(lambda: {r["traceID"].zfill(32) for r in request(url).get("traces", [])} == expected_ids)
                checks.append(filename + " Explore scope " + selected)
        if args.browser:
            chrome = shutil.which("google-chrome") or shutil.which("chromium")
            if not chrome:
                candidate = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                chrome = str(candidate) if candidate.is_file() else None
            if not chrome:
                raise RuntimeError("headless Chrome required for Grafana interpolation regression")
            state = output / "state"
            state.mkdir(exist_ok=True)
            start("fixture", "python:3.12-slim", [], None,
                          ["-e", "TEMPO_URL=http://" + name + "-tempo:3200",
                           "-v", str(Path(__file__).with_name("grafana_variable_fixture.py").resolve()) + ":/fixture.py:ro",
                           "-v", str(state) + ":/state"], ["python", "-u", "/fixture.py"])
            prom_config = {"global": {"scrape_interval": "1s"}, "scrape_configs": [
                {"job_name": "fixture", "static_configs": [{"targets": [name + "-fixture:8001"]}]}]}
            prom = start("prom", "prom/prometheus:v3.2.1", [9090], prom_config,
                         command_args=["--config.file=/config.yaml"])[9090]
            wait(lambda: len(request(prom + "/api/v1/query?" + urlencode(
                {"query": "adx_coordinator_node_capacity_cpu_millis"}))["data"]["result"]) == 2)
            rendered = subprocess.check_output(["helm", "template", "monitor", str(MONITOR)], text=True)
            resources = {(r["kind"], r["metadata"]["name"]): r
                         for r in yaml.safe_load_all(rendered) if r}
            mounts = []
            for cm, folder, destination in (
                ("grafana-datasources", "datasources", "/etc/grafana/provisioning/datasources"),
                ("grafana-dashboards-provider", "providers", "/etc/grafana/provisioning/dashboards"),
                ("grafana-dashboards", "dashboards", "/var/lib/grafana/dashboards"),
            ):
                directory = output / folder
                directory.mkdir(exist_ok=True)
                for filename, content in resources["ConfigMap", cm]["data"].items():
                    if cm == "grafana-datasources":
                        sources = yaml.safe_load(content)
                        urls = {"tempo": "http://" + name + "-fixture:8001/tempo",
                                "loki": "http://" + name + "-loki:3100",
                                "prometheus": "http://" + name + "-prom:9090"}
                        for source in sources["datasources"]:
                            if source["uid"] in urls:
                                source["url"] = urls[source["uid"]]
                        content = yaml.safe_dump(sources)
                    (directory / filename).write_text(content)
                mounts += ["-v", str(directory) + ":" + destination + ":ro"]
            gf = start("grafana", "grafana/grafana:11.5.2", [3000], None,
                       mounts + ["-e", "GF_AUTH_ANONYMOUS_ENABLED=true", "-e", "GF_AUTH_ANONYMOUS_ORG_ROLE=Admin",
                                 "-e", "GF_AUTH_BASIC_ENABLED=false", "-e", "GF_ANALYTICS_REPORTING_ENABLED=false"], [])[3000]
            wait(lambda: request(gf + "/api/health").get("database") == "ok")
            wait(lambda: request(gf + "/api/dashboards/uid/adx-environment-logs"))
            records = state / "requests.jsonl"
            for selected, expected in ((None, set(trace_ids.values())), ("cluster.a", {trace_ids["cluster.a"]})):
                case = "all" if selected is None else "specific"
                before = len(records.read_text().splitlines()) if records.exists() else 0
                url = gf + "/d/adx-environment-logs?" + urlencode(
                    {"from": "now-15m", "to": "now", **(
                        {"var-cluster": selected} if selected is not None else {})})
                with (output / ("chrome-" + case + ".html")).open("w") as dom, (
                    output / ("chrome-" + case + ".log")).open("w") as log:
                    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                                    "--disable-dev-shm-usage", "--disable-background-networking", "--no-first-run",
                                    "--user-data-dir=" + str(output / ("chrome-profile-" + case)),
                                    "--window-size=1800,3000", "--virtual-time-budget=20000", "--dump-dom", url],
                                   stdout=dom, stderr=log, check=True, timeout=60)
                received = [json.loads(line) for line in records.read_text().splitlines()[before:]] if records.exists() else []
                queries = [row for row in received if "resource.cluster" in row["query"]]
                assert queries, "Grafana did not issue its interpolated TraceQL query"
                assert all(row["status"] == 200 and set(row["ids"]) == expected for row in queries), queries
                checks.append("real Grafana custom-All interpolation" if selected is None
                              else "real Grafana literal cluster interpolation")
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        for role, identity in reversed(list(owned.items())):
            with (output / (role + ".log")).open("w") as stream:
                subprocess.run(["docker", "logs", identity], stdout=stream, stderr=subprocess.STDOUT, check=False)
            if subprocess.run(["docker", "rm", "-fv", identity], stdout=subprocess.DEVNULL, check=False).returncode:
                result["cleanup_errors"].append(role)
        if network and subprocess.run(["docker", "network", "rm", name], stdout=subprocess.DEVNULL, check=False).returncode:
            result["cleanup_errors"].append("network")
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    assert not result["cleanup_errors"], result
    print(f"PASS: {len(checks)} Loki/Tempo cluster-scope cases")


if __name__ == "__main__":
    main()
