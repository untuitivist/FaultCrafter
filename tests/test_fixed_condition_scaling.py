from __future__ import annotations

import json
from pathlib import Path
import re

import numpy as np
import pytest

from faultcrafter.fixed_condition_scaling import (
    FIXED_PHYSICAL_SCALES,
    FIXED_SCALING_PROTOCOL,
    prepare_fixed_scale_conditions,
)


BJTU_CASES = [
    ("20Hz_-10kN", [20, -10], [20, -10000], [0.2, -1]),
    ("20Hz_+0kN", [20, 0], [20, 0], [0.2, 0]),
    ("20Hz_+10kN", [20, 10], [20, 10000], [0.2, 1]),
    ("40Hz_-10kN", [40, -10], [40, -10000], [0.4, -1]),
    ("40Hz_+0kN", [40, 0], [40, 0], [0.4, 0]),
    ("40Hz_+10kN", [40, 10], [40, 10000], [0.4, 1]),
    ("60Hz_-10kN", [60, -10], [60, -10000], [0.6, -1]),
    ("60Hz_+0kN", [60, 0], [60, 0], [0.6, 0]),
    ("60Hz_+10kN", [60, 10], [60, 10000], [0.6, 1]),
]
CWRU_CASES = [
    ("1797rpm_0hp", [1797, 0], [29.95, 0], [0.2995, 0]),
    ("1772rpm_1hp", [1772, 1], [29.53333333333333, 745.6998715822702], [0.2953333333333333, 0.7456998715822702]),
    ("1750rpm_2hp", [1750, 2], [29.16666666666667, 1491.3997431645404], [0.2916666666666667, 1.4913997431645404]),
    ("1730rpm_3hp", [1730, 3], [28.83333333333333, 2237.0996147468106], [0.2883333333333333, 2.2370996147468106]),
]
HIT_CASES = [
    ("600rpm", [600], [10], [0.1, 0]),
    ("900rpm", [900], [15], [0.15, 0]),
    ("1200rpm", [1200], [20], [0.2, 0]),
]
CONDITION_CASES = [
    ("bjtu_rao_bogie", ["drive_frequency_hz", "lateral_load_kn"], *case)
    for case in BJTU_CASES
] + [
    ("cwru_motor_bearing_rig", ["shaft_speed_rpm", "motor_load_hp"], *case)
    for case in CWRU_CASES
] + [
    (device, ["shaft_speed_rpm"], *case)
    for device in ("hit_sm_spectraquest_mfs", "hit_sm_self_built")
    for case in HIT_CASES
]


@pytest.mark.parametrize("device,names,condition,raw,physical,coordinates", CONDITION_CASES)
def test_all_formal_conditions_use_fixed_coordinates(
    device, names, condition, raw, physical, coordinates,
) -> None:
    result = prepare_fixed_scale_conditions(names, raw, condition_dimension=2)
    assert result.protocol == FIXED_SCALING_PROTOCOL
    assert result.model_coordinates.dtype == np.float32
    assert result.canonical_values.dtype == np.float64
    np.testing.assert_allclose(result.canonical_values, physical, rtol=1e-14, atol=1e-14)
    np.testing.assert_array_equal(result.model_coordinates, np.asarray(coordinates, dtype=np.float32))


@pytest.mark.parametrize("raw,units", [
    ([900, 2], ["rpm", "hp"]),
    ([15, 1491.3997431645404], ["Hz", "W"]),
    ([0.015, 1.4913997431645404], ["kHz", "kW"]),
])
def test_equivalent_units_produce_identical_model_inputs(raw, units) -> None:
    result = prepare_fixed_scale_conditions(
        ["shaft_speed_rpm", "motor_load_hp"], raw, input_units=units,
    )
    assert result.canonical_names == ("shaft_speed_hz", "motor_load_w")
    assert result.canonical_units == ("Hz", "W")
    np.testing.assert_array_equal(result.model_coordinates, np.asarray([0.15, 1.4913997431645404], dtype=np.float32))


def test_training_matrix_and_single_request_have_identical_coordinates() -> None:
    names = ["drive_frequency_hz", "lateral_load_kn"]
    raw = np.asarray([[20, -10], [40, 0], [60, 10]], dtype=np.float64)
    before = raw.copy()
    training = prepare_fixed_scale_conditions(names, raw)
    for index, row in enumerate(raw):
        request = prepare_fixed_scale_conditions(names, dict(zip(names, row, strict=True)))
        np.testing.assert_array_equal(training.model_coordinates[index], request.model_coordinates)
    np.testing.assert_array_equal(raw, before)


def test_coordinates_do_not_depend_on_other_source_rows() -> None:
    names = ["shaft_speed_rpm"]
    narrow = prepare_fixed_scale_conditions(names, [[600], [900]])
    wide = prepare_fixed_scale_conditions(names, [[600], [900], [60000]])
    np.testing.assert_array_equal(narrow.model_coordinates, wide.model_coordinates[:2])


def test_signed_values_and_extrapolation_are_not_clipped() -> None:
    result = prepare_fixed_scale_conditions(
        ["drive_frequency_hz", "lateral_load_kn"], [250, -30],
    )
    np.testing.assert_array_equal(result.model_coordinates, [2.5, -3.0])


def test_padding_does_not_invent_a_load_field() -> None:
    result = prepare_fixed_scale_conditions(["shaft_speed_rpm"], [[600], [900]], condition_dimension=2)
    assert result.canonical_names == ("shaft_speed_hz",)
    assert result.canonical_values.shape == (2, 1)
    np.testing.assert_array_equal(result.model_coordinates[:, 1], [0, 0])


def test_drive_frequency_and_shaft_frequency_remain_distinct_quantities() -> None:
    result = prepare_fixed_scale_conditions(
        ["drive_frequency_hz", "shaft_speed_rpm"], [20, 1200],
    )
    assert result.canonical_names == ("drive_frequency_hz", "shaft_speed_hz")
    np.testing.assert_array_equal(result.model_coordinates, np.asarray([0.2, 0.2], dtype=np.float32))
    with pytest.raises(ValueError, match="incompatible"):
        prepare_fixed_scale_conditions(["drive_frequency_hz"], [1200], input_units=["rpm"])


@pytest.mark.parametrize("dimension", [0, 1, -1, 2.0, True, "2"])
def test_invalid_condition_dimensions_are_rejected(dimension) -> None:
    with pytest.raises(ValueError, match="condition dimension"):
        prepare_fixed_scale_conditions(["shaft_speed_rpm", "motor_load_hp"], [900, 0], condition_dimension=dimension)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1e50])
def test_nonfinite_model_coordinates_are_rejected(value) -> None:
    with pytest.raises(ValueError, match="finite"):
        prepare_fixed_scale_conditions(["shaft_speed_hz"], [value])


def test_unknown_or_duplicate_physical_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="not declared"):
        prepare_fixed_scale_conditions(["unknown"], [1])
    with pytest.raises(ValueError, match="same canonical"):
        prepare_fixed_scale_conditions(["shaft_speed_rpm", "shaft_speed_hz"], [900, 15])


def test_fixed_scales_are_read_only_and_have_no_device_specific_entries() -> None:
    assert dict(FIXED_PHYSICAL_SCALES) == {
        "shaft_frequency": 100.0,
        "drive_frequency": 100.0,
        "force": 10000.0,
        "power": 1000.0,
    }
    with pytest.raises(TypeError):
        FIXED_PHYSICAL_SCALES["force"] = 1.0
