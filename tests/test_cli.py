from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from google_art import cli

runner = CliRunner()


def test_from_file_accepts_bom_without_positional_assets(monkeypatch, tmp_path: Path):
    assets_file = tmp_path / "assets.txt"
    assets_file.write_text(" first-id \n\nsecond-id\n", encoding="utf-8-sig")
    calls = []

    async def fake_download_many(options, **kwargs):
        calls.append((options, kwargs))
        return [tmp_path / "first.png", tmp_path / "second.png"]

    monkeypatch.setattr(cli, "download_many", fake_download_many)
    result = runner.invoke(cli.app, ["--from-file", str(assets_file), "--no-progress", "--jobs", "2"])
    assert result.exit_code == 0, result.output
    options, kwargs = calls[0]
    assert [option.asset for option in options] == ["first-id", "second-id"]
    assert kwargs == {"jobs": 2, "show_progress": False}
    assert "Saved 2 artworks" in result.output


@pytest.mark.parametrize(
    "arguments",
    [
        ["--size", "0"],
        ["--size", "-1"],
        ["--jobs", "0"],
        ["--net-concurrency", "0"],
        ["--per-asset-concurrency", "0"],
        ["--queue-size", "0"],
        ["--assembler", "unknown"],
        ["--format", "gif"],
    ],
)
def test_invalid_options_fail_before_download(monkeypatch, arguments):
    called = False

    async def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(cli, "download_many", forbidden)
    result = runner.invoke(cli.app, ["sample-id", *arguments])
    assert result.exit_code == 2, result.output
    assert not called


def test_batch_rejects_explicit_output_file_before_download(monkeypatch, tmp_path: Path):
    called = False

    async def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(cli, "download_many", forbidden)
    result = runner.invoke(cli.app, ["first-id", "second-id", "-o", str(tmp_path / "one.png")])
    assert result.exit_code == 2
    assert "output directory" in result.output
    assert not called


def test_nested_exception_groups_show_real_causes_without_interpreting_markup(monkeypatch):
    async def failing(*args, **kwargs):
        raise ExceptionGroup(
            "batch wrapper",
            [
                ExceptionGroup("worker wrapper", [RuntimeError("missing tile [red]42[/red]")]),
                ValueError("invalid manifest"),
                RuntimeError("invalid manifest"),
            ],
        )

    monkeypatch.setattr(cli, "download_many", failing)
    result = runner.invoke(cli.app, ["sample-id", "--no-progress"])
    assert result.exit_code == 1
    assert "missing tile [red]42[/red]" in result.output
    assert result.output.count("invalid manifest") == 1
    assert "batch wrapper" not in result.output
    assert "worker wrapper" not in result.output


def test_no_assets_produces_usage_error():
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 2
    assert "at least one asset" in result.output
