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

from typing import Any, Literal, overload

import yr

from ..types import (
    YR_GET_DEFAULT_TIMEOUT,
    YR_GET_TIMEOUT_BUFFER,
    CommandInfo,
    CommandResult,
)


class CommandHandle:
    """Handle for a background process running in the sandbox."""

    def __init__(self, pid: int, instance: Any) -> None:
        self.pid = pid
        self._instance = instance

    def wait(self, timeout: int | None = None) -> CommandResult:
        """Wait for the process to finish and return its captured output.

        Args:
            timeout: Maximum number of seconds to wait. ``None`` waits without
                a deadline.

        Returns:
            The process output and exit code. A timeout is reported with exit
            code ``-1`` by the sandbox runtime.
        """

        rpc_timeout = (
            -1
            if timeout is None
            else max(timeout + YR_GET_TIMEOUT_BUFFER, YR_GET_DEFAULT_TIMEOUT)
        )
        result = yr.get(
            self._instance.cmd_wait.invoke(pid=self.pid, timeout=timeout),
            timeout=rpc_timeout,
        )
        return CommandResult(
            stdout=result["stdout"],
            stderr=result["stderr"],
            exit_code=result["exit_code"],
        )

    def kill(self) -> bool:
        """Terminate the process and return whether it was found."""

        result = yr.get(self._instance.cmd_kill.invoke(pid=self.pid))
        return result["killed"]

    def send_stdin(self, data: str, eof: bool = False) -> None:
        """Write *data* to the process's stdin.

        Args:
            data: Text to write.
            eof: Close stdin after writing so the process observes EOF.

        Raises:
            RuntimeError: The process was not started with stdin enabled or
                the runtime rejected the write.
        """
        result = yr.get(
            self._instance.cmd_send_stdin.invoke(pid=self.pid, data=data, eof=eof)
        )
        if result.get("error"):
            raise RuntimeError(f"Failed to send stdin: {result['error']}")

    def close_stdin(self) -> None:
        """Close the process's stdin so it sees EOF."""
        self.send_stdin("", eof=True)


class Commands:
    """Client-side wrapper for command execution on the remote sandbox."""

    def __init__(self, instance: Any) -> None:
        self._instance = instance

    @overload
    def run(
        self,
        cmd: str,
        background: Literal[False] = False,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: int = 60,
        stdin: Literal[False] = False,
    ) -> CommandResult: ...

    @overload
    def run(
        self,
        cmd: str,
        background: Literal[True],
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: int = 60,
        stdin: bool = False,
    ) -> CommandHandle: ...

    def run(
        self,
        cmd: str,
        background: bool = False,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: int = 60,
        stdin: bool = False,
    ) -> CommandResult | CommandHandle:
        """Execute a command in the sandbox.

        Args:
            cmd: Shell command to execute.
            background: Return a process handle without waiting when true.
            envs: Environment variables for the command.
            cwd: Working directory for the command.
            timeout: Maximum foreground execution time in seconds.
            stdin: Keep stdin open for a background process.

        Returns:
            A completed result for foreground execution or a process handle
            for background execution.

        Raises:
            ValueError: ``stdin`` is requested for foreground execution.
            RuntimeError: The runtime cannot start a background process.
        """
        if stdin and not background:
            raise ValueError("stdin=True requires background=True")

        if background:
            result = yr.get(
                self._instance.cmd_start.invoke(
                    cmd=cmd, envs=envs, cwd=cwd, want_stdin=stdin
                )
            )
            if result.get("error"):
                raise RuntimeError(f"Failed to start command: {result['error']}")
            return CommandHandle(result["pid"], self._instance)

        rpc_timeout = max(timeout + YR_GET_TIMEOUT_BUFFER, YR_GET_DEFAULT_TIMEOUT)
        result = yr.get(
            self._instance.cmd_run.invoke(cmd=cmd, envs=envs, cwd=cwd, timeout=timeout),
            timeout=rpc_timeout,
        )
        return CommandResult(
            stdout=result["stdout"],
            stderr=result["stderr"],
            exit_code=result["exit_code"],
        )

    def list(self) -> list[CommandInfo]:
        """Return snapshots of processes tracked by this sandbox."""

        result = yr.get(self._instance.cmd_list.invoke())
        return [
            CommandInfo(
                pid=int(process["pid"]),
                command=str(process["cmd"]),
                running=bool(process["running"]),
            )
            for process in result["processes"]
        ]

    def kill(self, pid: int) -> bool:
        """Terminate a tracked process and return whether it was found."""

        result = yr.get(self._instance.cmd_kill.invoke(pid=pid))
        return result["killed"]

    def send_stdin(self, pid: int, data: str, eof: bool = False) -> None:
        """Write *data* to the stdin of process *pid*.

        Args:
            pid: Tracked process ID.
            data: Text to write.
            eof: Close stdin after writing so the process observes EOF.

        Raises:
            RuntimeError: The process was not started with stdin enabled or
                the runtime rejected the write.
        """
        result = yr.get(
            self._instance.cmd_send_stdin.invoke(pid=pid, data=data, eof=eof)
        )
        if result.get("error"):
            raise RuntimeError(f"Failed to send stdin: {result['error']}")

    def close_stdin(self, pid: int) -> None:
        """Close the stdin of process *pid* so it sees EOF."""
        self.send_stdin(pid, "", eof=True)
