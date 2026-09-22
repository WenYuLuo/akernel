import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


class EnsureAdxCertificatesTest(unittest.TestCase):
    def test_generates_distinct_verified_component_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "adx"
            script = Path(__file__).with_name("ensure-adx-certs.sh")
            environment = dict(os.environ, AKERNEL_ADX_STATE_DIR=str(state))

            subprocess.run([script], check=True, env=environment)
            initial = {
                p.relative_to(state): p.read_bytes()
                for p in state.rglob("*")
                if p.is_file()
            }
            subprocess.run([script], check=True, env=environment)
            self.assertEqual(
                initial,
                {
                    p.relative_to(state): p.read_bytes()
                    for p in state.rglob("*")
                    if p.is_file()
                },
            )

            tls = state / "tls"
            certificates = []
            for identity in ("master", "node-1", "api-server", "edge"):
                certificate = tls / f"{identity}.pem"
                subprocess.run(
                    ["openssl", "verify", "-CAfile", tls / "ca.pem", certificate],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                certificates.append(certificate.read_bytes())
                self.assertTrue((tls / f"{identity}.der").is_file())
            self.assertEqual(len(set(certificates)), len(certificates))
            self.assertEqual(
                stat.S_IMODE((state / "secrets/admin-key").stat().st_mode),
                0o600,
            )


if __name__ == "__main__":
    unittest.main()
