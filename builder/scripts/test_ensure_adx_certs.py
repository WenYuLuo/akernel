import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


class EnsureAdxCertificatesTest(unittest.TestCase):
    def test_only_generates_and_reuses_public_https_identity(self):
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
            self.assertEqual({p.name for p in tls.iterdir()}, {"edge-public.pem", "edge-public.key"})
            subprocess.run(
                ["openssl", "verify", "-CAfile", tls / "edge-public.pem", tls / "edge-public.pem"],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual(
                stat.S_IMODE((state / "secrets/admin-key").stat().st_mode),
                0o600,
            )


if __name__ == "__main__":
    unittest.main()
