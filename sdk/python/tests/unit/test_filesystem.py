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

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from yr.cli.exec import CopyRequest, ExecConnection

from akernel_sdk.filesystem import Filesystem
from akernel_sdk.types import EntryInfo


class FilesystemTest(unittest.TestCase):
    def setUp(self):
        self.instance = MagicMock()
        self.files = Filesystem(self.instance, instance_id="sandbox-id")

    def test_read_text_and_bytes(self):
        with patch(
            "akernel_sdk.filesystem.yr.get",
            side_effect=[
                {"data": "hello", "error": None},
                {"data": "0001ff", "error": None},
            ],
        ):
            self.assertEqual(self.files.read("/tmp/a"), "hello")
            self.assertEqual(self.files.read("/tmp/b", format="bytes"), b"\x00\x01\xff")

    def test_read_rejects_unknown_format(self):
        with self.assertRaisesRegex(ValueError, "format"):
            self.files.read("/tmp/a", format="json")

    def test_list_returns_entry_info(self):
        with patch(
            "akernel_sdk.filesystem.yr.get",
            return_value={
                "entries": [
                    {
                        "name": "file.txt",
                        "path": "/tmp/file.txt",
                        "type": "file",
                        "size": 3,
                        "permissions": "rw-r--r--",
                        "modified_time": 1.0,
                    }
                ],
                "error": None,
            },
        ):
            result = self.files.list("/tmp")
        self.assertEqual(
            result,
            [
                EntryInfo(
                    name="file.txt",
                    path="/tmp/file.txt",
                    type="file",
                    size=3,
                    permissions="rw-r--r--",
                    modified_time=1.0,
                )
            ],
        )

    def test_copy_from_local_inside_running_event_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            source.write_text("hello", encoding="utf-8")

            async def copy_inside_event_loop():
                self.files.copy_from_local(str(source), "/tmp/source.txt")

            with (
                patch.object(
                    self.files,
                    "_get_connection",
                    return_value=("gateway", "443", "sandbox-id", "token", True),
                ),
                patch("yr.cli.exec.choose_cp_mode", return_value=False),
                patch(
                    "yr.cli.exec.copy_to_remote",
                    new_callable=AsyncMock,
                ) as copy_to_remote,
            ):
                asyncio.run(copy_inside_event_loop())

        copy_to_remote.assert_awaited_once_with(
            ExecConnection(
                host="gateway",
                port="443",
                use_ssl=True,
                verify_server=False,
                token="token",
            ),
            CopyRequest(
                instance="sandbox-id",
                local_path=str(source),
                remote_path="/tmp/source.txt",
            ),
        )


if __name__ == "__main__":
    unittest.main()
