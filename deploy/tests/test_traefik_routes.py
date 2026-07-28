# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

"""Keep Helm and standalone sandbox routes aligned."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELM_CONFIG = (
    ROOT
    / "deploy/akernel/charts/core/templates/traefik/configmap.yaml"
).read_text(encoding="utf-8")
STANDALONE_CONFIG = (
    ROOT / "deploy/standalone/start.sh"
).read_text(encoding="utf-8")


class TraefikSandboxRoutesTest(unittest.TestCase):
    def test_sandbox_control_api_routes_to_frontend(self) -> None:
        self.assertIn("PathPrefix(`/api/sandbox`)", HELM_CONFIG)
        self.assertIn(r"PathPrefix(\`/api/sandbox\`)", STANDALONE_CONFIG)

    def test_direct_api_uses_a_high_priority_frontend_router(self) -> None:
        self.assertIn(
            'rule: "PathPrefix(`/direct/`) || Path(`/direct`)"',
            HELM_CONFIG,
        )
        self.assertIn(
            r'rule: "PathPrefix(\`/direct/\`) || Path(\`/direct\`)"',
            STANDALONE_CONFIG,
        )
        self.assertIn("priority: 100", HELM_CONFIG)
        self.assertIn("priority: 100", STANDALONE_CONFIG)


if __name__ == "__main__":
    unittest.main()
