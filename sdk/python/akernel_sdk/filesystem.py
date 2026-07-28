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

"""Backend-neutral filesystem facade."""

from __future__ import annotations

from typing import Literal, overload

from ._backends.base import FilesystemDriver
from .types import EntryInfo


class Filesystem:
    """Filesystem operations for one remote sandbox."""

    def __init__(self, driver: FilesystemDriver) -> None:
        self._driver = driver

    @overload
    def read(self, path: str, format: Literal["text"] = "text") -> str: ...

    @overload
    def read(self, path: str, format: Literal["bytes"]) -> bytes: ...

    def read(self, path: str, format: str = "text") -> str | bytes:
        """Read a file as text or bytes."""

        if format not in ("text", "bytes"):
            raise ValueError("format must be 'text' or 'bytes'")
        return self._driver.read(path, binary=format == "bytes")

    def write(self, path: str, data: str | bytes) -> EntryInfo:
        """Write text or bytes and return remote metadata."""

        return self._driver.write(path, data)

    def list(self, path: str, depth: int = 1) -> list[EntryInfo]:
        """List entries below a path."""

        return self._driver.list(path, depth)

    def exists(self, path: str) -> bool:
        """Return whether a path exists."""

        return self._driver.exists(path)

    def remove(self, path: str) -> None:
        """Remove a file or directory."""

        self._driver.remove(path)

    def rename(self, old_path: str, new_path: str) -> EntryInfo:
        """Rename a remote path."""

        return self._driver.rename(old_path, new_path)

    def make_dir(self, path: str) -> bool:
        """Create a directory and report whether it was newly created."""

        return self._driver.make_dir(path)

    def get_info(self, path: str) -> EntryInfo:
        """Return metadata for a remote path."""

        return self._driver.get_info(path)

    def copy_from_local(self, local_path: str, remote_path: str) -> None:
        """Copy a local file or directory into the sandbox."""

        self._driver.copy_from_local(local_path, remote_path)

    def copy_to_local(self, remote_path: str, local_path: str) -> None:
        """Copy a sandbox file or directory to the local machine."""

        self._driver.copy_to_local(remote_path, local_path)
