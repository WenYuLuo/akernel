#!/usr/bin/env python3
"""Download the exact Buildkite ADX release recorded in the lock file."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from verify_adx_release import verify


DEFAULT_API_BASE = "https://api.buildkite.com/v2"


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward the Buildkite bearer token to object storage."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        redirected = super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )
        if redirected is None:
            return None
        old_origin = urllib.parse.urlsplit(request.full_url).netloc
        new_origin = urllib.parse.urlsplit(new_url).netloc
        if old_origin != new_origin:
            redirected.remove_header("Authorization")
        return redirected


def _request_json(url: str, token: str) -> tuple[list[dict[str, Any]], Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
        return payload, response.headers


def _find_artifact(
    api_base: str,
    source: dict[str, Any],
    artifact_path: str,
    token: str,
) -> dict[str, Any]:
    organization = urllib.parse.quote(str(source["organization"]), safe="")
    pipeline = urllib.parse.quote(str(source["pipeline"]), safe="")
    build = int(source["build"])
    base = (
        f"{api_base.rstrip('/')}/organizations/{organization}/pipelines/"
        f"{pipeline}/builds/{build}/artifacts"
    )
    matches: list[dict[str, Any]] = []
    page = 1
    while True:
        artifacts, _ = _request_json(f"{base}?per_page=100&page={page}", token)
        matches.extend(item for item in artifacts if item.get("path") == artifact_path)
        if len(artifacts) < 100:
            break
        page += 1
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one Buildkite artifact {artifact_path!r}, "
            f"found {len(matches)}"
        )
    return matches[0]


def fetch(
    destination: Path,
    lock_path: Path,
    token: str,
    api_base: str = DEFAULT_API_BASE,
) -> None:
    """Fetch and atomically install the pinned ADX archive."""

    if destination.exists():
        verify(destination, lock_path)
        return
    if not token:
        raise ValueError("BUILDKITE_API_TOKEN is required to fetch the ADX release")

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    source = lock.get("source") or {}
    if source.get("provider") != "buildkite":
        raise ValueError("ADX release lock source is not Buildkite")
    artifact_path = str((lock.get("archive") or {})["path"])
    artifact = _find_artifact(api_base, source, artifact_path, token)
    download_url = artifact.get("download_url")
    if not isinstance(download_url, str) or not download_url:
        raise ValueError("Buildkite artifact has no download URL")

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        request = urllib.request.Request(
            download_url, headers={"Authorization": f"Bearer {token}"}
        )
        opener = urllib.request.build_opener(_SafeRedirectHandler())
        with opener.open(request, timeout=120) as response:
            with temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
        verify(temporary, lock_path)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "adx-release.lock.json",
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    args = parser.parse_args()
    fetch(
        args.output,
        args.lock,
        os.environ.get("BUILDKITE_API_TOKEN", ""),
        args.api_base,
    )
    print(f"ADX release ready at {args.output}")


if __name__ == "__main__":
    main()
