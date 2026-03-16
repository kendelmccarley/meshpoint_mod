"""Check whether a newer version is available on GitHub."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/device", tags=["device"])

MESHPOINT_DIR = "/opt/meshpoint"
CACHE_TTL_SECONDS = 300

_cache: dict[str, object] = {"result": None, "expires": 0}


async def _git_output(*args: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=MESHPOINT_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        return stdout.decode().strip()
    except OSError:
        return None


@router.get("/update-check")
async def update_check():
    now = time.time()
    if _cache["result"] and now < _cache["expires"]:
        return _cache["result"]

    local_sha = await _git_output("rev-parse", "HEAD")
    remote_raw = await _git_output("ls-remote", "origin", "HEAD")
    remote_sha = remote_raw.split()[0] if remote_raw else None

    if not local_sha or not remote_sha:
        result = {
            "update_available": False,
            "local_sha": local_sha,
            "remote_sha": remote_sha,
            "error": "Could not reach GitHub",
        }
    else:
        result = {
            "update_available": local_sha != remote_sha,
            "local_sha": local_sha[:8],
            "remote_sha": remote_sha[:8],
        }

    _cache["result"] = result
    _cache["expires"] = now + CACHE_TTL_SECONDS

    return result
