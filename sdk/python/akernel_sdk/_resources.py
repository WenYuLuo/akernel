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

"""Backend-neutral resource discovery through the frontend API."""

import json
import os
from collections.abc import Mapping
from urllib import request
from urllib.error import HTTPError, URLError

from ._addresses import api_endpoint_from_env
from ._resource_api import parse_resource_nodes
from .cli import _create_ssl_context
from .types import NodeInfo


def resources() -> list[NodeInfo]:
    """Return cluster resources through stable AKernel value types."""

    endpoint = api_endpoint_from_env()
    token = os.environ.get("AKERNEL_TOKEN", "").strip()
    if not token:
        raise RuntimeError("AKERNEL_TOKEN is not set")
    req = request.Request(
        f"{endpoint.base_url()}/global-scheduler/resources",
        method="GET",
        headers={"X-Auth": token, "Type": "json", "Accept": "application/json"},
    )
    try:
        with request.urlopen(req, context=_create_ssl_context()) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        body = error.read().decode("utf-8")
        raise RuntimeError(
            f"resource query failed: HTTP {error.code} {body}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"resource query failed: {error}") from error

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("resource query returned invalid JSON") from error
    if not isinstance(payload, Mapping):
        return []
    return parse_resource_nodes(payload)
