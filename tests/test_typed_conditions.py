from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import torch

from faultcrafter.compact_deployment import CompactDeploymentManifest
from faultcrafter.compact_inference import is_device_lora, load_compact_model, sample_compact_signal
from faultcrafter.condition_guidance import condition_slope_penalty, typed_condition_projectors
from faultcrafter.condition_migration import migrate_condition_projection
from faultcrafter.config import load_config
from faultcrafter.typed_conditions import TYPED_CONDITION_PROTOCOL, encode_model_conditions, encode_typed_conditions, prepare_condition_request
from faultcrafter.unified_generator import UnifiedSignalGenerator


GRIDS = {
    "bjtu_rao_bogie": np.asarray([[speed, load] for speed in (20, 40, 60) for load in (-10, 0, 10)], dtype=np.float32),
    "cwru_motor_bearing_rig": np.asarray([[1797, 0], [1772, 1], [1750, 2], [1730, 3]], dtype=np.float32),
    "hit_sm_spectraquest_mfs": np.asarray([[600], [900], [1200]], dtype=np.float32),
    "hit_sm_self_built": np.asarray([[600], [900], [1200]], dtype=np.float32),
}


def arguments(dimension=8, devices=1):
    return {"num_faults": 1, "num_fault_groups": 1, "condition_dimension": dimension,
            "num_devices": devices, "base_channels": 8, "context_dimension": 16,
            "attention_heads": 2, "style_attention_rank": 4, "style_token_count": 3,
            "lora_rank": 4, "attention_radius": 2, "attention_chunk_size": 32}


@pytest.mark.parametrize("load,expected", [(-10, -1), (0, 0), (10, 1), (20, 2)])
def test_masks_do_not_collide_with_zero_negative_or_extrapolated_values(load, expected):
    encoded = encode_typed_conditions(["drive_frequency_hz", "lateral_load_kn"], [40, load])
    np.testing.assert_allclose(encoded, [0, 0.4, expected, 0, 0, 1, 1, 0])
    missing = encode_typed_conditions(["drive_frequency_hz"], [40])
    assert missing[2] == 0 and missing[6] == 0
    assert encoded[6] == 1


def test_unit_and_field_order_equivalence():
    expected = encode_typed_conditions(["shaft_speed_rpm", "motor_load_hp"], [1772, 1])
    converted = encode_typed_conditions(["motor_load_hp", "shaft_speed_rpm"], [745.6998715822702, 1772 / 60], input_units=["W", "Hz"])
    np.testing.assert_array_equal(expected, converted)
    np.testing.assert_array_equal(expected[4:], [1, 0, 0, 1])


@pytest.mark.parametrize("values", [[float("nan")], [float("inf")], [1e100]])
def test_nonfinite_or_overflowed_values_rejected(values):
    with pytest.raises(ValueError):
        encode_typed_conditions(["shaft_speed_hz"], values)


def test_duplicate_physical_slot_rejected():
    with pytest.raises(ValueError):
        encode_typed_conditions(["motor_load_hp", "load_hp"], [1, 2])


def test_request_audit_reports_actual_eight_model_coordinates():
    parameters, audit = prepare_condition_request(["shaft_speed_rpm"], {"shaft_speed_rpm": 15}, input_units={"shaft_speed_rpm": "Hz"}, model_protocol=TYPED_CONDITION_PROTOCOL)
    assert parameters == {"shaft_speed_rpm": 900}
    assert audit["native_parameters"] == parameters
    assert audit["model_parameters"]["shaft_frequency_present"] == 1
    assert audit["model_parameters"]["force_present"] == 0
    assert audit["model_parameters"]["shaft_frequency_scaled"] == pytest.approx(0.15)
    assert len(audit["model_parameters"]) == 8


def test_encoding_ignores_device_statistics_and_matches_rows():
    device = SimpleNamespace(condition_protocol=TYPED_CONDITION_PROTOCOL, parameter_names=("shaft_speed_rpm",), parameter_mean=np.asarray([float("nan")]), parameter_standard_deviation=np.asarray([0]))
    matrix = encode_model_conditions(device, [[600], [900], [1200]], 8)
    for index, speed in enumerate((600, 900, 1200)):
        np.testing.assert_array_equal(matrix[index], encode_typed_conditions(device.parameter_names, [speed]))
    with pytest.raises(ValueError):
        encode_model_conditions(device, [900], 2)


def test_slope_regularizer_never_penalizes_masks_or_absent_quantities():
    device = SimpleNamespace(index=0, parameter_names=("shaft_speed_rpm", "motor_load_hp"), corpus=SimpleNamespace(parameter_matrix=GRIDS["cwru_motor_bearing_rig"]))
    geometry = typed_condition_projectors([device], {"generator": {"condition_retained_variance": 0.99}}, torch.device("cpu"))
    assert torch.count_nonzero(geometry.projectors[:, 4:]) == 0
    assert torch.count_nonzero(geometry.projectors[:, :, 4:]) == 0
    model = UnifiedSignalGenerator(**arguments())
    original = condition_slope_penalty(model, geometry)
    with torch.no_grad():
        model.style_field.query.shared.weight[:, 5:] += 1000
        model.style_field.query.shared.weight[:, 2:4] += 1000
    torch.testing.assert_close(condition_slope_penalty(model, geometry), original, rtol=0, atol=0)
    condition_slope_penalty(model, geometry).backward()
    assert torch.count_nonzero(model.style_field.query.shared.weight.grad[:, 5:]) == 0


@pytest.mark.parametrize("guidance_scale,guidance_mode", [(1.0, "linear"), (1.25, "linear"), (1.5, "conditional_rms_cap"), (1.5, "unit_peak_projection")])
def test_source_free_loader_and_web_request_share_typed_encoder(tmp_path, guidance_scale, guidance_mode):
    model_arguments = {**arguments(), "fault_identity_guidance_scale": guidance_scale, "fault_identity_guidance_mode": guidance_mode}
    model = UnifiedSignalGenerator(**model_arguments)
    shared = tmp_path / "shared_generator.pt"
    sampling = {"sampling_steps": 2, "terminal_time": 0.9, "stochastic_amplitude": False}
    torch.save({"format": "faultcrafter_compact_v1", "model_arguments": model_arguments, "input_condition_coordinates": TYPED_CONDITION_PROTOCOL, "state": {name: value for name, value in model.state_dict().items() if not is_device_lora(name)}, "sampling": sampling}, shared)
    digest = hashlib.sha256(shared.read_bytes()).hexdigest()
    directory = tmp_path / "device"
    directory.mkdir()
    adapter = directory / "device_lora.pt"
    torch.save({"device_id": "device", "shared_sha256": digest, "state": {name: value[0] for name, value in model.state_dict().items() if is_device_lora(name)}}, adapter)
    profile = {"route_id": "device.sensor", "device_id": "device", "dataset_id": "unit", "sensor_location": "sensor", "channel": "vibration", "signal_quantity": "acceleration", "physical_unit": "source_not_declared", "sample_rate_hz": 51200, "amplitude_method": "parent_long_signal_max_abs", "time_coordinate": "sample_index", "angle_coordinate": "shaft_phase", "condition_protocol": TYPED_CONDITION_PROTOCOL, "shared_sha256": digest, "parameter_names": ["shaft_speed_rpm"], "speed_parameter_index": 0, "speed_to_hz": 1 / 60, "faults": {"normal": {"fault_index": 0, "fault_group_index": 0}}}
    profile_path = directory / "signal_profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    isolated, restored, sampling = load_compact_model(shared, adapter, profile_path)
    assert isolated.fault_identity_guidance_scale == guidance_scale
    assert isolated.fault_identity_guidance_mode == guidance_mode
    manifest = CompactDeploymentManifest.load(tmp_path)
    assert manifest.device("device").parameter_names == ("shaft_speed_rpm",)
    def capture(model, noise, coordinates, fault, group, route, speed, sample_rate, **kwargs):
        return coordinates.clone(), speed.clone(), sample_rate.clone()
    with patch("faultcrafter.compact_inference.sample_unified_generator", side_effect=capture):
        native = sample_compact_signal(isolated, restored, sampling, condition_parameters=[900], fault_label="normal", length=64, seed=42)
        converted = sample_compact_signal(isolated, restored, sampling, condition_parameters=[15], condition_units=["Hz"], fault_label="normal", length=64, seed=42)
    for actual, expected in zip(converted, native, strict=True):
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    torch.testing.assert_close(native[0][0], torch.from_numpy(encode_typed_conditions(["shaft_speed_rpm"], [900])))
    assert native[1].item() == pytest.approx(15)
    restored["condition_protocol"] = "invalid"
    profile_path.write_text(json.dumps(restored), encoding="utf-8")
    with pytest.raises(ValueError):
        load_compact_model(shared, adapter, profile_path)
