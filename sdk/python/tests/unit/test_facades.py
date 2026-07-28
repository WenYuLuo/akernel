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

import unittest
from unittest.mock import MagicMock

from akernel_sdk.commands import CommandHandle, Commands
from akernel_sdk.filesystem import Filesystem
from akernel_sdk.types import CommandResult


class CommandFacadeTest(unittest.TestCase):
    def test_foreground_and_background_operations_delegate_to_driver(self):
        driver = MagicMock()
        driver.run.return_value = CommandResult("ok", "", 0)
        driver.start.return_value = 17
        commands = Commands(driver)

        self.assertEqual(commands.run("echo ok"), CommandResult("ok", "", 0))
        driver.run.assert_called_once_with(
            "echo ok",
            envs=None,
            cwd=None,
            timeout=60,
        )

        handle = commands.run("cat", background=True, stdin=True)
        self.assertIsInstance(handle, CommandHandle)
        self.assertEqual(handle.pid, 17)
        handle.send_stdin("hello", eof=True)
        driver.send_stdin.assert_called_once_with(17, "hello", True)


class FilesystemFacadeTest(unittest.TestCase):
    def test_read_format_is_validated_and_translated(self):
        driver = MagicMock()
        driver.read.side_effect = ["hello", b"\x00\x01"]
        files = Filesystem(driver)

        self.assertEqual(files.read("/tmp/a"), "hello")
        self.assertEqual(files.read("/tmp/b", format="bytes"), b"\x00\x01")
        self.assertEqual(
            driver.read.call_args_list[0].kwargs,
            {"binary": False},
        )
        self.assertEqual(
            driver.read.call_args_list[1].kwargs,
            {"binary": True},
        )
        with self.assertRaisesRegex(ValueError, "format"):
            files.read("/tmp/c", format="json")


if __name__ == "__main__":
    unittest.main()
