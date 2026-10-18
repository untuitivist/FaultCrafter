from __future__ import annotations

import numpy as np
import pytest

from faultcrafter.condition_units import (
    canonicalize_condition_values,
    convert_condition_values,
    model_condition_request,
    unit_control_metadata,
)


@pytest.mark.parametrize("value,unit", [(1800.0, "rpm"), (30.0, "Hz"), (0.03, "kHz")])
def test_rotational_units_have_identical_native_and_canonical_inputs(value, unit) -> None:
    native, audit = model_condition_request(
        ["shaft_speed_rpm"], {"shaft_speed_rpm": value},
        input_units={"shaft_speed_rpm": unit},
    )
    assert native == {"shaft_speed_rpm": 1800.0}
    assert audit["canonical_parameters"] == {"shaft_speed_hz": 30.0}
    assert audit["requested_parameters"] == {"shaft_speed_rpm": value}


def test_preprocessing_matrix_and_single_inference_share_conversion() -> None:
    names, matrix = canonicalize_condition_values(
        ["shaft_speed_rpm", "motor_load_hp"], [[1800.0, 1.0], [1200.0, 2.0]],
    )
    assert names == ("shaft_speed_hz", "motor_load_w")
    np.testing.assert_allclose(matrix, [[30.0, 745.6998715822702], [20.0, 1491.3997431645404]])
    restored = convert_condition_values(
        ["shaft_speed_rpm", "motor_load_hp"], matrix, input_units=["Hz", "W"],
    )
    np.testing.assert_allclose(restored, [[1800.0, 1.0], [1200.0, 2.0]], rtol=1e-14)


def test_signed_force_and_drive_frequency_keep_their_physical_meaning() -> None:
    names, converted = canonicalize_condition_values(
        ["drive_frequency_hz", "lateral_load_kn"], [0.04, -10000.0],
        input_units=["kHz", "N"],
    )
    assert names == ("drive_frequency_hz", "lateral_load_n")
    np.testing.assert_array_equal(converted, [40.0, -10000.0])
    options = unit_control_metadata("drive_frequency_hz")["unit_options"]
    assert {option["unit"] for option in options} == {"Hz", "kHz"}


@pytest.mark.parametrize("name,unit", [
    ("drive_frequency_hz", "rpm"), ("lateral_load_kn", "hp"),
    ("motor_load_hp", "kN"), ("shaft_speed_rpm", "W"),
])
def test_incompatible_physical_quantities_are_rejected(name, unit) -> None:
    with pytest.raises(ValueError, match="incompatible"):
        convert_condition_values([name], [10.0], input_units=[unit])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_values_are_rejected(value) -> None:
    with pytest.raises(ValueError, match="finite"):
        convert_condition_values(["shaft_speed_rpm"], [value])


def test_unit_fields_and_parameter_fields_must_match() -> None:
    with pytest.raises(ValueError, match="exactly"):
        convert_condition_values(["shaft_speed_rpm"], [30], input_units={"drive_frequency_hz": "Hz"})
    with pytest.raises(ValueError, match="declared fields"):
        model_condition_request(["shaft_speed_rpm"], {"drive_frequency_hz": 30})
    with pytest.raises(ValueError, match="same canonical"):
        canonicalize_condition_values(["shaft_speed_rpm", "shaft_speed_hz"], [1800, 30])


def test_conversion_does_not_clip_extrapolated_values() -> None:
    native = convert_condition_values(["shaft_speed_rpm"], [0.1], input_units=["kHz"])
    np.testing.assert_array_equal(native, [6000.0])


def test_unknown_quantities_and_overflow_are_rejected() -> None:
    with pytest.raises(ValueError, match="not declared"):
        convert_condition_values(["unknown"], [1.0])
    with pytest.raises(ValueError, match="overflowed"):
        canonicalize_condition_values(["shaft_speed_rpm"], [1e308], input_units=["kHz"])
