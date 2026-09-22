#!/usr/bin/env python3

"""Focused tests for the standalone deployment driver."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


SCRIPT = Path(__file__).with_name("start.sh")


class StartScriptTest(unittest.TestCase):
    def test_health_probe_reads_token_from_curl_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = root / "admin-key"
            token.write_text("test-secret\n", encoding="utf-8")
            fake_curl = root / "curl"
            captured = root / "curl-input"
            fake_curl.write_text(
                textwrap.dedent(
                    """\
                    #!/bin/sh
                    cat > "$CAPTURED_CURL_INPUT"
                    printf '%s\\n' "$@" > "$CAPTURED_CURL_ARGS"
                    """
                ),
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{root}:{environment['PATH']}",
                    "CAPTURED_CURL_INPUT": str(captured),
                    "CAPTURED_CURL_ARGS": str(root / "curl-args"),
                }
            )
            command = (
                f"source {SCRIPT!s}; "
                f"TOKEN_FILE={token!s}; "
                "probe_adx_health https://127.0.0.1:8443/healthz"
            )
            subprocess.run(
                ["bash", "-c", command],
                check=True,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                captured.read_text(encoding="utf-8"),
                'header = "X-Auth: test-secret"\n',
            )
            arguments = (root / "curl-args").read_text(encoding="utf-8")
            self.assertIn("https://127.0.0.1:8443/healthz", arguments)
            self.assertNotIn("test-secret", arguments)

    def test_health_probe_waits_for_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-key"
            command = (
                f"source {SCRIPT!s}; "
                f"TOKEN_FILE={missing!s}; "
                "! probe_adx_health https://127.0.0.1:8443/healthz"
            )
            subprocess.run(
                ["bash", "-c", command],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_node_health_probe_executes_inside_node_container(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_docker = root / "docker"
            captured = root / "docker-args"
            fake_docker.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURED_DOCKER_ARGS\"\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            environment = os.environ.copy()
            environment["CAPTURED_DOCKER_ARGS"] = str(captured)
            command = (
                f"source {SCRIPT!s}; "
                f"DOCKER_CMD={fake_docker!s}; "
                "NODE_CONTAINER_NAME=test-node; "
                "probe_node_health http://127.0.0.1:18080/healthz"
            )
            subprocess.run(
                ["bash", "-c", command],
                check=True,
                env=environment,
                capture_output=True,
                text=True,
            )

            arguments = captured.read_text(encoding="utf-8")
            self.assertTrue(arguments.startswith("exec\ntest-node\ncurl\n"))
            self.assertIn("http://127.0.0.1:18080/healthz", arguments)


if __name__ == "__main__":
    unittest.main()
