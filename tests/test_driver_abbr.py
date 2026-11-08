"""Tes driver_abbr_from_row: driver tanpa `code` di API (kolom NaN) tidak boleh jadi 'nan'."""
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastf1.ergast import Ergast

import fetch_f1_data as f
from test_fetch_results_rows import _mrdata, _race, _result


def _without_code(pos, driver_id, given, family, pts=0):
    res = _result(pos, "XXX", pts)
    del res["Driver"]["code"]
    res["Driver"].update(driverId=driver_id, givenName=given, familyName=family)
    return res


def test_valid_code_is_used():
    assert f.driver_abbr_from_row({"driverCode": "NOR", "familyName": "Norris"}) == "NOR"


def test_nan_code_falls_back_to_family_name():
    assert f.driver_abbr_from_row({"driverCode": np.nan, "familyName": "Hirakawa"}) == "HIR"
    assert f.driver_abbr_from_row({"driverCode": pd.NA, "familyName": "Hirakawa"}) == "HIR"
    assert f.driver_abbr_from_row({"driverCode": None, "familyName": "Hirakawa"}) == "HIR"
    assert f.driver_abbr_from_row({"driverCode": "nan", "familyName": "Hirakawa"}) == "HIR"


def test_accents_and_spaces_are_normalised():
    assert f.driver_abbr_from_row({"driverCode": np.nan, "familyName": "Câmara"}) == "CAM"
    assert f.driver_abbr_from_row({"driverCode": np.nan, "familyName": "de Vries"}) == "DEV"


def test_nothing_usable_returns_empty_string_not_nan():
    assert f.driver_abbr_from_row({"driverCode": np.nan, "familyName": np.nan}) == ""
    assert f.driver_abbr_from_row({}) == ""


def test_override_wins(monkeypatch):
    monkeypatch.setitem(f._ABBR_OVERRIDES, "camara", "RCA")
    assert f.driver_abbr_from_row({"driverId": "camara", "driverCode": np.nan, "familyName": "Câmara"}) == "RCA"


def test_race_results_with_new_drivers_have_valid_abbr():
    payload = _mrdata([_race(19, "Results", [
        _result(1, "NOR", 25),
        _without_code(15, "hirakawa", "Ryo", "Hirakawa"),
        _without_code(16, "camara", "Rafael", "Câmara"),
    ])])
    with patch.object(Ergast, "_get", return_value=payload):
        rows = f.fetch_results_rows(Ergast(), 2026, "Race")
    assert [r["driver_abbr"] for r in rows] == ["NOR", "HIR", "CAM"]
    assert rows[1]["driver_name"] == "Ryo Hirakawa"
