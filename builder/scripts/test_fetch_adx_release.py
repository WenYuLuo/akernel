from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from threading import Thread
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_adx_release import fetch


class FetchAdxReleaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive, self.lock = self._fixture()
        self.authorization: list[str | None] = []
        self.download_authorization: list[str | None] = []

        test = self

        class PayloadHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                test.download_authorization.append(
                    self.headers.get("Authorization")
                )
                if self.path != "/payload":
                    self.send_error(404)
                    return
                payload = test.archive.read_bytes()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.payload_server = ThreadingHTTPServer(
            ("127.0.0.1", 0), PayloadHandler
        )
        self.payload_base = (
            f"http://127.0.0.1:{self.payload_server.server_port}"
        )
        self.payload_thread = Thread(
            target=self.payload_server.serve_forever, daemon=True
        )
        self.payload_thread.start()
        self.addCleanup(self.payload_server.server_close)
        self.addCleanup(self.payload_thread.join, 2)
        self.addCleanup(self.payload_server.shutdown)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                test.authorization.append(self.headers.get("Authorization"))
                if self.path.startswith("/organizations/org/pipelines/pipe/builds/7/artifacts"):
                    payload = json.dumps(
                        [
                            {
                                "path": "out/buildkite/adx-release.tar.gz",
                                "download_url": f"{test.api_base}/download",
                            }
                        ]
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if self.path == "/download":
                    self.send_response(302)
                    self.send_header("Location", f"{test.payload_base}/payload")
                    self.end_headers()
                    return
                self.send_error(404)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.api_base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.shutdown)

    def _fixture(self) -> tuple[Path, Path]:
        payload = b"rrt"
        digest = hashlib.sha256(payload).hexdigest()
        manifest = {
            "schema_version": 1,
            "commit": "a" * 40,
            "dirty": False,
            "target": "x86_64-unknown-linux-gnu",
            "profile": "release",
            "files": {"runtime/rrt-runtime": digest},
        }
        archive = self.root / "source.tar.gz"
        with tarfile.open(archive, "w:gz") as package:
            for name, value in (
                ("manifest.json", json.dumps(manifest).encode()),
                ("runtime/rrt-runtime", payload),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(value)
                package.addfile(info, io.BytesIO(value))
        lock = {
            "schema_version": 1,
            "source": {
                "provider": "buildkite",
                "organization": "org",
                "pipeline": "pipe",
                "build": 7,
                "commit": "a" * 40,
            },
            "archive": {
                "path": "out/buildkite/adx-release.tar.gz",
                "size": archive.stat().st_size,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            },
            "package": {
                "target": "x86_64-unknown-linux-gnu",
                "profile": "release",
                "files": {"runtime/rrt-runtime": digest},
            },
        }
        lock_path = self.root / "lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        return archive, lock_path

    def test_downloads_and_verifies_the_locked_artifact(self) -> None:
        destination = self.root / "downloaded.tar.gz"

        fetch(destination, self.lock, "secret", self.api_base)

        self.assertEqual(destination.read_bytes(), self.archive.read_bytes())
        self.assertEqual(self.authorization, ["Bearer secret", "Bearer secret"])
        self.assertEqual(self.download_authorization, [None])

    def test_reuses_a_verified_local_archive_without_a_token(self) -> None:
        destination = self.root / "downloaded.tar.gz"
        destination.write_bytes(self.archive.read_bytes())

        fetch(destination, self.lock, "", self.api_base)

        self.assertEqual(self.authorization, [])

    def test_rejects_an_unverified_cached_archive(self) -> None:
        destination = self.root / "downloaded.tar.gz"
        destination.write_bytes(b"wrong")

        with self.assertRaisesRegex(ValueError, "size"):
            fetch(destination, self.lock, "", self.api_base)


if __name__ == "__main__":
    unittest.main()
