# Copyright (c) 2026 Ant Group Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Opt-in runc executable-loss regression on a task-owned standalone container."""

import hashlib
import json
import os
import subprocess
import time
import unittest
import uuid
from pathlib import Path

import httpx

from akernel_sdk import Sandbox
from akernel_sdk._addresses import api_endpoint_from_env
from tests.e2e.full.test_redis_lifecycle import _Redis
from tests.e2e.run import _capture_redis_inventory

_ENABLED = (
    os.environ.get("AKERNEL_RUN_INTEGRATION") == "1"
    and os.environ.get("AKERNEL_TEST_DESTRUCTIVE_FAULTS") == "1"
    and bool(os.environ.get("AKERNEL_SERVER_ADDRESS"))
    and bool(os.environ.get("AKERNEL_REDIS_HOST"))
    and bool(os.environ.get("AKERNEL_TEST_CONTAINER"))
    and bool(os.environ.get("AKERNEL_TEST_CONTAINER_ID"))
)

# Emit only ownership/retention evidence; OCI specs and metadata may contain secrets.
_SNAPSHOT = r"""
import hashlib,json,os,sys
from pathlib import Path
physical,marker,pid,cgroup=sys.argv[1:]
paths={
 "runtime":Path('/run/sandboxd/runc')/physical,
 "bundle":Path('/home/akernel/sandboxd/root/containers')/physical,
 "storage":Path('/home/akernel/filestore/.runc')/physical,
 "netns":Path('/run/netns')/('runc-'+physical),
}
bundle=paths['bundle']
state=paths['runtime']/'state.json'
if state.exists():
 data=json.loads(state.read_text())
 pid=str(data.get('init_process_pid') or pid)
config=bundle/'config.json'
if config.exists():
 raw=json.loads(config.read_text()).get('linux',{}).get('cgroupsPath','')
 if raw: cgroup=str(Path('/sys/fs/cgroup')/raw.lstrip('/'))
alive=False
if int(pid)>1:
 try: os.kill(int(pid),0);alive=True
 except ProcessLookupError: pass
file=bundle/'rootfs'/'tmp'/marker
result={k:p.exists() for k,p in paths.items()}
result.update(metadata=(bundle/'meta.pb').exists(),
 marker_sha256=hashlib.sha256(file.read_bytes()).hexdigest() if file.exists() else None,
 init_pid=int(pid),init_alive=alive,cgroup_path=cgroup,
 cgroup_exists=bool(cgroup) and Path(cgroup).exists(),
 mounts=[line for line in Path('/proc/self/mountinfo').read_text().splitlines()
         if physical in line])
print(json.dumps(result))
"""


@unittest.skipUnless(
    _ENABLED, "requires isolated standalone node and explicit fault opt-in"
)
class RuncDeleteRetryIntegrationTest(unittest.TestCase):
    def test_missing_runc_retains_ownership_then_monitor_cleans_after_restore(self):
        container = os.environ.get("AKERNEL_TEST_CONTAINER", "")
        expected = os.environ.get("AKERNEL_TEST_CONTAINER_ID", "")
        self.assertTrue(
            container and len(expected) == 64,
            "set task-owned container name and full ID",
        )
        output = Path(os.environ["AKERNEL_TEST_FAULT_OUTPUT"])
        output.mkdir(parents=True, exist_ok=True)
        name = "runc-delete-retry-" + uuid.uuid4().hex[:12]
        marker = name + ".bin"
        payload = uuid.uuid4().bytes * 4096
        backup = "/usr/local/bin/runc." + name
        namespace = os.environ.get("AKERNEL_REDIS_NAMESPACE", "akernel")
        control = f"adx:{{{namespace}}}:control:v1"
        evidence = {
            "status": "failed",
            "observations": [],
            "public_delete_requests_before_cleanup": 0,
        }
        sandbox = None
        hidden = False
        physical, pid, cgroup = "", 0, ""

        def docker(*args):
            identity = subprocess.check_output(
                ["docker", "inspect", "--format", "{{.Id}}", container], text=True
            ).strip()
            self.assertEqual(identity, expected, "task container identity changed")
            return subprocess.check_output(
                ["docker", "exec", container, *args], text=True
            )

        def record():
            client = _Redis()
            try:
                raw = client.call("HGET", control, "environment:" + sandbox.id)
                return json.loads(raw) if raw else None
            finally:
                client.close()

        def snapshot(stage):
            nonlocal pid, cgroup
            state = json.loads(
                docker("python3", "-c", _SNAPSHOT, physical, marker, str(pid), cgroup)
            )
            pid, cgroup = state["init_pid"], state["cgroup_path"]
            current = record()
            result = (current or {}).get("result") or {}
            state.update(
                stage=stage,
                time=time.time(),
                state=result.get("state"),
                resources_held=result.get("resources_held"),
                assignment=(current or {}).get("assignment"),
            )
            evidence["observations"].append(state)
            (output / "runc-delete-retry.json").write_text(
                json.dumps(evidence, indent=2) + "\n"
            )
            return state

        def restore():
            nonlocal hidden
            if hidden:
                docker(
                    "python3",
                    "-c",
                    "import os,sys; os.rename(sys.argv[1],'/usr/local/bin/runc')",
                    backup,
                )
                hidden = False

        try:
            self.assertFalse(
                _capture_redis_inventory()["states"], "deployment must start empty"
            )
            self.assertEqual(
                docker(
                    "python3",
                    "-c",
                    "from pathlib import Path; "
                    "print(len(list(Path('/run/sandboxd/runc').glob('*'))))",
                ).strip(),
                "0",
            )
            kwargs = {
                "name": name,
                "runtime": "runc",
                "detached": True,
                "cpu": 1000,
                "memory": 2048,
                "schedule_timeout": 120,
            }
            if os.environ.get("AKERNEL_TEST_IMAGE"):
                kwargs["image"] = os.environ["AKERNEL_TEST_IMAGE"]
            sandbox = Sandbox(**kwargs)
            self.assertEqual(
                sandbox.commands.run("printf before-delete").stdout, "before-delete"
            )
            sandbox.files.write("/tmp/" + marker, payload)
            physical_ids = json.loads(
                docker(
                    "python3",
                    "-c",
                    "import json; from pathlib import Path; "
                    "print(json.dumps([p.name for p in "
                    "Path('/run/sandboxd/runc').iterdir()]))",
                )
            )
            self.assertEqual(len(physical_ids), 1)
            physical = physical_ids[0]
            running = snapshot("running")
            self.assertEqual(
                running["marker_sha256"], hashlib.sha256(payload).hexdigest()
            )
            self.assertTrue(
                all(
                    running[k]
                    for k in (
                        "metadata",
                        "storage",
                        "runtime",
                        "netns",
                        "init_alive",
                        "cgroup_exists",
                    )
                )
            )
            evidence["environment_id"] = sandbox.id
            evidence["physical_id"] = physical
            docker(
                "python3",
                "-c",
                "import os,sys; p='/usr/local/bin/runc'; "
                "assert os.path.realpath(p)==p and not os.path.exists(sys.argv[1]); "
                "os.rename(p,sys.argv[1])",
                backup,
            )
            hidden = True
            with httpx.Client(verify=False, trust_env=False, timeout=90) as client:
                evidence["public_delete_requests_before_cleanup"] += 1
                response = client.delete(
                    api_endpoint_from_env().base_url()
                    + "/api/environment/v1/environments/"
                    + sandbox.id,
                    headers={"X-Auth": os.environ["AKERNEL_TOKEN"]},
                )
            evidence["delete_status"] = response.status_code
            self.assertGreaterEqual(
                response.status_code, 500, "failed deletion must not report success"
            )
            hold = time.monotonic() + 12
            while True:
                failed = snapshot("runtime-unavailable")
                self.assertEqual(failed["state"], "Failed")
                self.assertTrue(failed["resources_held"])
                self.assertEqual(failed["assignment"], running["assignment"])
                self.assertEqual(failed["marker_sha256"], running["marker_sha256"])
                self.assertTrue(
                    all(
                        failed[k]
                        for k in (
                            "metadata",
                            "storage",
                            "runtime",
                            "netns",
                            "init_alive",
                            "cgroup_exists",
                        )
                    )
                )
                if time.monotonic() >= hold:
                    break
                time.sleep(2)
            restore()
            evidence["restored_at"] = time.time()
            # Only read Redis and physical state here. No SDK/API delete is issued.
            deadline = time.monotonic() + 90
            while True:
                cleaned = snapshot("await-automatic-cleanup")
                physical_clean = not any(
                    cleaned[k]
                    for k in (
                        "metadata",
                        "storage",
                        "runtime",
                        "bundle",
                        "netns",
                        "init_alive",
                        "cgroup_exists",
                        "mounts",
                    )
                )
                if physical_clean and cleaned["resources_held"] is not True:
                    break
                self.assertLess(
                    time.monotonic(),
                    deadline,
                    "upstream monitor did not retry cleanup after restoring runc",
                )
                time.sleep(1)
            evidence["automatic_cleanup_seconds"] = (
                cleaned["time"] - evidence["restored_at"]
            )
            evidence["automatic_cleanup_verified"] = True
            self.assertEqual(evidence["public_delete_requests_before_cleanup"], 1)
            evidence["status"] = "passed"
        finally:
            restore()
            # Retire the remaining Failed catalog record only after the automatic
            # physical-cleanup assertion, keeping that action distinct in evidence.
            if sandbox is not None:
                sandbox.kill()
                Sandbox.delete(name)
                evidence["terminal_record_retired_by_explicit_cleanup"] = True
                self.assertIsNone(record())
            (output / "runc-delete-retry.json").write_text(
                json.dumps(evidence, indent=2) + "\n"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
