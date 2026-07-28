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
from unittest.mock import MagicMock, patch

from akernel_sdk._backends.openyuanrong_sdk_commands import CommandHandle, Commands
from akernel_sdk.types import CommandInfo, CommandResult


class CommandsTest(unittest.TestCase):
    def setUp(self):
        self.instance = MagicMock()

    def test_list_returns_command_info(self):
        token = object()
        self.instance.cmd_list.invoke.return_value = token
        with patch(
            "akernel_sdk._backends.openyuanrong_sdk_commands.yr.get",
            return_value={
                "processes": [
                    {"pid": 42, "cmd": "sleep 30", "running": True},
                ]
            },
        ):
            result = Commands(self.instance).list()
        self.assertEqual(
            result,
            [CommandInfo(pid=42, command="sleep 30", running=True)],
        )

    def test_foreground_command_uses_one_run_rpc_for_long_timeout(self):
        token = object()
        self.instance.cmd_run.invoke.return_value = token
        with patch(
            "akernel_sdk._backends.openyuanrong_sdk_commands.yr.get",
            return_value={"stdout": "ok\n", "stderr": "", "exit_code": 0},
        ) as get:
            result = Commands(self.instance).run("echo ok", timeout=60)

        self.assertEqual(result, CommandResult("ok\n", "", 0))
        self.instance.cmd_run.invoke.assert_called_once_with(
            cmd="echo ok", envs=None, cwd=None, timeout=60
        )
        self.instance.cmd_start.invoke.assert_not_called()
        get.assert_called_once_with(token, timeout=300)

    def test_foreground_command_rejects_stdin(self):
        with self.assertRaisesRegex(ValueError, "background=True"):
            Commands(self.instance).run("cat", stdin=True)
        self.instance.cmd_run.invoke.assert_not_called()
        self.instance.cmd_start.invoke.assert_not_called()

    def test_background_command_returns_handle(self):
        token = object()
        self.instance.cmd_start.invoke.return_value = token
        with patch(
            "akernel_sdk._backends.openyuanrong_sdk_commands.yr.get",
            return_value={"pid": 99, "error": None},
        ):
            result = Commands(self.instance).run(
                "cat", background=True, stdin=True
            )

        self.assertIsInstance(result, CommandHandle)
        self.assertEqual(result.pid, 99)
        self.instance.cmd_start.invoke.assert_called_once_with(
            cmd="cat", envs=None, cwd=None, want_stdin=True
        )

    def test_background_start_error_is_reported(self):
        self.instance.cmd_start.invoke.return_value = object()
        with patch(
            "akernel_sdk._backends.openyuanrong_sdk_commands.yr.get",
            return_value={"pid": -1, "error": "exec failed"},
        ):
            with self.assertRaisesRegex(RuntimeError, "exec failed"):
                Commands(self.instance).run("bad-command", background=True)

    def test_handle_wait_uses_one_wait_rpc(self):
        token = object()
        self.instance.cmd_wait.invoke.return_value = token
        with patch(
            "akernel_sdk._backends.openyuanrong_sdk_commands.yr.get",
            return_value={"stdout": "done", "stderr": "", "exit_code": 0},
        ) as get:
            result = CommandHandle(7, self.instance).wait(timeout=60)

        self.assertEqual(result, CommandResult("done", "", 0))
        self.instance.cmd_wait.invoke.assert_called_once_with(pid=7, timeout=60)
        get.assert_called_once_with(token, timeout=300)

    def test_handle_wait_without_timeout_is_unbounded(self):
        token = object()
        self.instance.cmd_wait.invoke.return_value = token
        with patch(
            "akernel_sdk._backends.openyuanrong_sdk_commands.yr.get",
            return_value={"stdout": "done", "stderr": "", "exit_code": 0},
        ) as get:
            CommandHandle(7, self.instance).wait()

        get.assert_called_once_with(token, timeout=-1)


if __name__ == "__main__":
    unittest.main()
