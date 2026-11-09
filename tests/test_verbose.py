"""Tes flag --verbose pada fetch_f1_data: default run tidak memunculkan [DEBUG], --verbose memunculkan."""
from unittest.mock import patch
import pytest
from fastf1.ergast import Ergast
import fetch_f1_data as f
from test_fetch_results_rows import _mrdata, _race, _result


def _sample_payload():
    return _mrdata([
        _race(1, "Results", [_result(1, "VER", 25)]),
    ])


def _sample_quali_payload():
    return _mrdata([
        _race(1, "QualifyingResults", [_result(1, "VER", 0, grid=1)]),
    ])


def test_argparse_verbose_flag():
    parser = f.build_parser()
    args_default = parser.parse_args(["--season", "2026"])
    assert args_default.verbose is False

    args_verbose = parser.parse_args(["--season", "2026", "--verbose"])
    assert args_verbose.verbose is True


def test_fetch_results_rows_default_prints_no_debug(capsys):
    with patch.object(Ergast, "_get", return_value=_sample_payload()):
        f.fetch_results_rows(Ergast(), 2026, "Race", verbose=False)

    captured = capsys.readouterr()
    assert "[DEBUG]" not in captured.out


def test_fetch_results_rows_verbose_prints_debug(capsys):
    with patch.object(Ergast, "_get", return_value=_sample_payload()):
        f.fetch_results_rows(Ergast(), 2026, "Race", verbose=True)

    captured = capsys.readouterr()
    assert "[DEBUG]" in captured.out


def test_fetch_qualifying_rows_default_prints_no_debug(capsys):
    with patch.object(Ergast, "_get", return_value=_sample_quali_payload()):
        f.fetch_qualifying_rows(Ergast(), 2026, verbose=False)

    captured = capsys.readouterr()
    assert "[DEBUG]" not in captured.out


def test_fetch_qualifying_rows_verbose_prints_debug(capsys):
    with patch.object(Ergast, "_get", return_value=_sample_quali_payload()):
        f.fetch_qualifying_rows(Ergast(), 2026, verbose=True)

    captured = capsys.readouterr()
    assert "[DEBUG]" in captured.out
