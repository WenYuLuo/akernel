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

"""Stable errors raised at the AKernel backend boundary."""


class InvalidBackendError(ValueError):
    """The configured backend identifier is not supported."""


class BackendNotInstalledError(ImportError):
    """The selected backend dependency is not installed."""


class UnsupportedBackendFeatureError(ValueError):
    """The selected backend cannot preserve a requested AKernel feature."""


class BackendOperationError(RuntimeError):
    """A backend operation failed."""
