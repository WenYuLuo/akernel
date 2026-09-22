import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_adx_release import stage
from verify_adx_release import verify


class VerifyAdxReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _fixture(self):
        payload = b"rrt"
        payload_digest = hashlib.sha256(payload).hexdigest()
        manifest = {
            "schema_version": 1,
            "commit": "a" * 40,
            "dirty": False,
            "target": "x86_64-unknown-linux-gnu",
            "profile": "release",
            "files": {"runtime/rrt-runtime": payload_digest},
        }
        archive = self.root / "release.tar.gz"
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
            "source": {"commit": "a" * 40},
            "archive": {
                "size": archive.stat().st_size,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            },
            "package": {
                "target": "x86_64-unknown-linux-gnu",
                "profile": "release",
                "files": {"runtime/rrt-runtime": payload_digest},
            },
        }
        lock_path = self.root / "lock.json"
        lock_path.write_text(json.dumps(lock))
        return archive, lock_path

    def test_accepts_the_exact_pinned_bytes(self):
        archive, lock = self._fixture()
        verify(archive, lock)

    def test_rejects_an_altered_archive(self):
        archive, lock = self._fixture()
        archive.write_bytes(archive.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "size"):
            verify(archive, lock)

    def test_stages_only_the_verified_consumed_files(self):
        archive, lock = self._fixture()
        destination = self.root / "staged"

        stage(archive, destination, lock)

        self.assertEqual(
            (destination / "runtime/rrt-runtime").read_bytes(), b"rrt"
        )
        self.assertFalse((destination / "manifest.json").exists())

    def test_refuses_to_replace_an_existing_stage(self):
        archive, lock = self._fixture()
        destination = self.root / "staged"
        destination.mkdir()

        with self.assertRaisesRegex(ValueError, "already exists"):
            stage(archive, destination, lock)


if __name__ == "__main__":
    unittest.main()
