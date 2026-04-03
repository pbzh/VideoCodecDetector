"""Shared constants and helper functions for video codec utilities.

This module centralises data that is duplicated across the two GUI tools:
- The set of recognised video file extensions.
- The list of known codec identifiers.
- A thin wrapper around ``ffprobe`` that returns the JSON output.
- A helper to check that ``ffprobe`` is available on the PATH.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict

# ---------------------------------------------------------------------------
# Video file extensions (case‑insensitive).  The list mirrors the one used in
# ``VideoCodecDetector.py`` and covers the extensions historically handled by
# ``VideoCodecRename_1.2.py``.
# ---------------------------------------------------------------------------
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mov",
        ".mp4",
        ".mkv",
        ".avi",
        ".m4v",
        ".mpg",
        ".mpeg",
        ".m2ts",
        ".mts",
        ".ts",
        ".wmv",
        ".flv",
        ".webm",
        ".3gp",
        ".f4v",
    }
)

# ---------------------------------------------------------------------------
# Known codec identifiers – used for counting / colour mapping.
# ---------------------------------------------------------------------------
VIDEO_CODECS: tuple[str, ...] = (
    "utvideo",
    "dnxhd",
    "h265",
    "h264",
    "xvid",
    "mpeg4",
    "msmpeg4v3",
    "error",
)

# Template for per‑codec counters (all zero).  Each script can copy this dict
# when it needs a fresh counter set.
VIDEO_CODEC_COUNTS_TEMPLATE: Dict[str, int] = {c: 0 for c in VIDEO_CODECS}

# ---------------------------------------------------------------------------
# ffprobe helpers
# ---------------------------------------------------------------------------
def probe_file(path: Path) -> dict:
    """Run ``ffprobe`` on *path* and return the parsed JSON dictionary.

    The command mirrors the call used in ``VideoCodecDetector.py``.  A timeout of
    30 seconds is applied to avoid hanging on corrupted files.
    """
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


def ffprobe_available() -> bool:
    """Return ``True`` if the ``ffprobe`` executable can be invoked.

    Used by the UI to warn the user when FFmpeg is missing.
    """
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
