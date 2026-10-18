from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from faultcrafter.services.application import RuntimeApplication
from faultcrafter.services.model_defaults import EXPERIMENT32_COMPACT_PATH
from faultcrafter.compact_deployment import CompactDeploymentManifest, CompactJiTRuntime
from faultcrafter.compact_inference import folded_device_lora, is_device_lora
from faultcrafter.unified_generator import UnifiedSignalGenerator


def compact_fixture(root: Path) -> Path:
    root.mkdir()
    arguments = {
        "num_faults": 1, "num_fault_groups": 1, "condition_dimension": 2,
        "num_devices": 1, "base_channels": 8, "context_dimension": 32,
        "attention_heads": 4, "style_attention_rank": 4, "style_token_count": 2,
        "lora_rank": 4, "attention_radius": 2, "attention_chunk_size": 32,
    }
    model = UnifiedSignalGenerator(**arguments)
    shared_path = root / "shared_generator.pt"
    torch.save({
        "format": "faultcrafter_compact_v1", "model_arguments": arguments,
        "input_condition_coordinates": "physical_raw_folded_into_device_lora",
        "state": {name: value for name, value in model.state_dict().items() if not is_device_lora(name)},
        "sampling": {"sampling_steps": 2, "terminal_time": 0.9, "stochastic_amplitude": True},
    }, shared_path)
    digest = hashlib.sha256(shared_path.read_bytes()).hexdigest()
    directory = root / "device"
    directory.mkdir()
    torch.save({
        "device_id": "device", "shared_sha256": digest,
        "state": folded_device_lora(model, 0, [600.0, 0.0], [100.0, 1.0]),
    }, directory / "device_lora.pt")
    profile = {
        "route_id": "device.sensor.channel", "dataset_id": "dataset", "device_id": "device",
        "sensor_location": "sensor", "channel": "channel", "signal_quantity": "acceleration",
        "physical_unit": "source_not_declared", "sample_rate_hz": 1000,
        "amplitude_method": "parent_long_signal_max_abs", "time_coordinate": "sample_index / sample_rate_hz",
        "angle_coordinate": "integrated shaft speed", "shared_sha256": digest,
        "parameter_names": ["shaft_speed_rpm", "lateral_load_kn"],
        "speed_parameter_index": 0, "speed_to_hz": 1.0 / 60.0,
        "faults": {"normal": {"fault_index": 0, "fault_group_index": 0}},
    }
    (directory / "signal_profile.json").write_text(json.dumps(profile), encoding="utf-8")
    return root


def test_compact_web_uses_only_selected_package_without_legacy_manifest(tmp_path, monkeypatch) -> None:
    root = compact_fixture(tmp_path / "compact")
    def forbidden(*arguments, **keywords):
        raise AssertionError("legacy model or normalization manifest must not be loaded")
    monkeypatch.setattr("faultcrafter.unified_jit_deployment.UnifiedDeploymentManifest.load", forbidden)
    monkeypatch.setattr("faultcrafter.unified_jit_deployment.UnifiedJiTRuntime", forbidden)
    application = RuntimeApplication(root, compute_device="cpu")
    public = application.public_manifest()
    assert public["condition_unit_protocol"] == "physical_si_v1"
    assert "signal_profile" in public["runtime_contract"]
    assert "parameter_mean" not in json.dumps(public)
    assert "parameter_standard_deviation" not in json.dumps(public)
    for parameter in public["devices"][0]["parameters"]:
        assert parameter["minimum"] <= parameter["initial"] <= parameter["maximum"]
        assert parameter["step"] > 0
        assert parameter["measured"] == []
    payload = {
        "device_id": "device", "fault_id": "normal", "length": 512, "seed": 17,
        "condition_parameters": {"shaft_speed_rpm": 10.0, "lateral_load_kn": -1000.0},
        "condition_units": {"shaft_speed_rpm": "Hz", "lateral_load_kn": "N"},
    }
    result = application.generate(payload)
    assert result["condition_parameters"] == {"shaft_speed_rpm": 600.0, "lateral_load_kn": -1.0}
    assert result["condition_conversion"]["canonical_parameters"] == {"shaft_speed_hz": 10.0, "lateral_load_n": -1000.0}
    assert len(result["physical_signal"]) == 512


def test_compact_runtime_unit_changes_preserve_waveform_and_all_asset_bytes(tmp_path) -> None:
    root = compact_fixture(tmp_path / "compact")
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}
    runtime = CompactJiTRuntime(CompactDeploymentManifest.load(root), device="cpu")
    request = {"device_id": "device", "fault_id": "normal", "length": 512, "seed": 91}
    native = runtime.generate(**request, condition_parameters={"shaft_speed_rpm": 600.0, "lateral_load_kn": -1.0})
    alternate = runtime.generate(
        **request, condition_parameters={"shaft_speed_rpm": 0.01, "lateral_load_kn": -1000.0},
        condition_units={"shaft_speed_rpm": "kHz", "lateral_load_kn": "N"},
    )
    np.testing.assert_array_equal(native.normalized_signal, alternate.normalized_signal)
    np.testing.assert_array_equal(native.physical_signal, alternate.physical_signal)
    assert native.predicted_amplitude == alternate.predicted_amplitude
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before}


def test_compact_identity_rejects_hidden_source_statistics(tmp_path) -> None:
    root = compact_fixture(tmp_path / "compact")
    profile_path = root / "device/signal_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["source_mean"] = [1.0, 2.0]
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="undeclared runtime state"):
        CompactDeploymentManifest.load(root)


def test_invalid_units_rejected_before_loading_inference_weights(tmp_path) -> None:
    root = compact_fixture(tmp_path / "compact")
    application = RuntimeApplication(root, compute_device="cpu")
    with pytest.raises(ValueError, match="incompatible"):
        application.generate({
            "device_id": "device", "fault_id": "normal", "length": 512, "seed": 17,
            "condition_parameters": {"shaft_speed_rpm": 10.0, "lateral_load_kn": 0.0},
            "condition_units": {"shaft_speed_rpm": "W", "lateral_load_kn": "kN"},
        })
    assert application._runtime is None


def test_default_web_rejects_benchmark_weights_in_release_directory(tmp_path, monkeypatch) -> None:
    root = tmp_path / EXPERIMENT32_COMPACT_PATH
    root.parent.mkdir(parents=True)
    compact_fixture(root)
    monkeypatch.setattr("faultcrafter.services.application.default_model_root", lambda: root)
    with pytest.raises(ValueError, match="not a benchmark fold"):
        RuntimeApplication()
