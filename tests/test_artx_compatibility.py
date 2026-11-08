from __future__ import annotations

import importlib
import re
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from artx.models import DownloadSize
from google_art import AsyncGoogleArtDownloader, AsyncOptions, DownloadOptions, GoogleArtDownloader

ROOT = Path(__file__).resolve().parents[1]


def test_artx_deprecated_namespace_forwards_to_new_models():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        legacy = importlib.import_module("googleart_download.models")
    assert legacy.DownloadSize is DownloadSize


def test_original_google_art_api_remains_distinct_and_available():
    from google_art.async_downloader import AsyncOptions as OldAsyncOptions
    from google_art.downloader import DownloadOptions as OldDownloadOptions

    assert OldAsyncOptions is AsyncOptions
    assert OldDownloadOptions is DownloadOptions
    assert DownloadOptions(asset="example", max_edge=2048).max_edge == 2048
    assert AsyncGoogleArtDownloader.__module__ == "google_art.async_downloader"
    assert GoogleArtDownloader.__module__ == "google_art.downloader"


@pytest.mark.parametrize(
    ("arguments", "expected_option"),
    [
        (["-m", "artx"], "--resume-batch"),
        ([str(ROOT / "main.py")], "--resume-batch"),
        (["-m", "google_art.cli"], "--from-file"),
    ],
)
def test_module_entry_points_show_their_own_cli(arguments, expected_option):
    result = subprocess.run(
        [sys.executable, *arguments, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    plain_output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stdout)
    assert expected_option in plain_output
    assert "DeprecationWarning" not in result.stderr
