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

"""Request a whole GPU device.

The cluster must advertise a matching GPU resource. Set AKERNEL_GPU_MODEL to a
scheduler-visible normalized model such as ``a10``, or leave it unset to accept
any GPU model.
"""

import os

from akernel_sdk import Sandbox


def main() -> None:
    model = os.environ.get("AKERNEL_GPU_MODEL", "").strip()
    with Sandbox(xpu=f"gpu:{model}:1", cpu=1000, memory=2048) as sandbox:
        result = sandbox.commands.run("nvidia-smi -L")
        assert result.exit_code == 0, result.stderr
        print(result.stdout)


if __name__ == "__main__":
    main()
