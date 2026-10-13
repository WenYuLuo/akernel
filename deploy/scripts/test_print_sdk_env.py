#!/usr/bin/env python3

# Copyright (c) 2026 Ant Group Corporation.
# SPDX-License-Identifier: Apache-2.0
"""Verify SDK endpoints are read from the deployed ADX public Service."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent


class PrintSdkEnvTest(unittest.TestCase):
    def test_direct_service_addresses_and_custom_ports(self):
        for host, control, data in [
            ("192.0.2.7", "443", "80"),
            ("adx.example.test", "9443", "9080"),
            ("2001:db8::7", "443", "8080"),
        ]:
            with self.subTest(host=host), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                scripts = root / "deploy/scripts"
                scripts.mkdir(parents=True)
                for name in ("common.sh", "print-sdk-env.sh", "get-adx-admin-key.sh"):
                    shutil.copy2(SCRIPTS / name, scripts / name)
                (root / "deploy/terraform/aliyun").mkdir(parents=True)
                profile = root / ".akernel/test"
                profile.mkdir(parents=True)
                (profile / "config.env").write_text("CORE_NAMESPACE=test-ns\n")
                kubeconfig = profile / "kubeconfig"
                kubeconfig.touch()
                binaries = root / "bin"
                binaries.mkdir()
                (binaries / "terraform").write_text("""#!/usr/bin/env bash
case "$*" in
 *kubeconfig_path) echo "$FAKE_KUBECONFIG" ;;
 *core_namespace) echo test-ns ;;
 *monitor_namespace) echo monitor ;;
 *) exit 2 ;;
esac
""")
                (binaries / "kubectl").write_text("""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALLS"
case "$*" in
 *"get secret akernel-adx-tls"*) printf YWR4LXRlc3Qta2V5 ;;
 *"get svc akernel-adx-public"*loadBalancer*) printf '%s' "$FAKE_HOST" ;;
 *"get svc akernel-adx-public"*'name=="control"'*) printf '%s' "$CONTROL" ;;
 *"get svc akernel-adx-public"*'name=="data"'*) printf '%s' "$DATA" ;;
 *"get svc grafana"*) exit 0 ;;
 *) exit 3 ;;
esac
""")
                for binary in binaries.iterdir():
                    binary.chmod(0o755)
                env = dict(
                    os.environ,
                    PATH=f"{binaries}:{os.environ['PATH']}",
                    FAKE_KUBECONFIG=str(kubeconfig),
                    FAKE_HOST=host,
                    CONTROL=control,
                    DATA=data,
                    CALLS=str(root / "calls"),
                )
                subprocess.run(
                    [
                        scripts / "print-sdk-env.sh",
                        "--vendor",
                        "aliyun",
                        "--env",
                        "test",
                    ],
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                result = subprocess.check_output(
                    [
                        "bash",
                        "-c",
                        'source "$1"; printf "%s\\n%s\\n" "$AKERNEL_SERVER_ADDRESS" "${AKERNEL_GATEWAY_ADDRESS:-}"',
                        "_",
                        str(profile / "sdk.env"),
                    ],
                    text=True,
                    env={
                        k: v for k, v in env.items() if k != "AKERNEL_GATEWAY_ADDRESS"
                    },
                )
                address = f"[{host}]" if ":" in host else host
                expected_control = (
                    address if control == "443" else f"{address}:{control}"
                )
                expected_data = (
                    ""
                    if (control, data) == ("443", "80")
                    else f"http://{address}" + (f":{data}" if data != "80" else "")
                )
                self.assertEqual(result.splitlines(), [expected_control, expected_data])
                self.assertNotIn("traefik", (root / "calls").read_text())
                self.assertEqual((profile / "sdk.env").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
