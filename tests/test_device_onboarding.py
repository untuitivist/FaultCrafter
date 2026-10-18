from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from faultcrafter.services.device_onboarding import DeviceOnboarding
from faultcrafter.services.model_defaults import EXPERIMENT32_COMPACT_PATH
from faultcrafter.compact_deployment import CompactDeploymentManifest
from faultcrafter.condition_units import convert_condition_values
from faultcrafter.device_lora_training import FoldedTrainingQuery
from faultcrafter.compact_inference import folded_device_lora
from faultcrafter.unified_generator import UnifiedSignalGenerator
from faultcrafter.device_onboarding import read_signal, validate_manifest, write_json


PROJECT = Path(__file__).resolve().parents[1]
RELEASE = PROJECT / EXPERIMENT32_COMPACT_PATH


def manifest():
    return {"schema": "faultcrafter_device_upload_v1", "device_id": "new_bearing", "dataset_id": "new_dataset",
            "sensor_location": "housing", "channel": "vibration_1", "sample_rate_hz": 64000,
            "physical_unit": "source_not_declared", "sampling_policy": "declared_rate_sample_index",
            "parameter_names": ["shaft_speed_rpm", "radial_force_n"], "fixed_conditions": {"shaft_torque_nm": 0.7},
            "records": [{"record_id": split, "file": f"{split}.npy", "split": split, "fault": "normal",
                         "conditions": {"shaft_speed_rpm": 1500, "radial_force_n": 1000}} for split in ("train", "validation")]}


@pytest.fixture
def release():
    if not RELEASE.is_dir():
        pytest.skip("Full-data release is not installed")
    return RELEASE


def test_radial_force_preserves_distinct_meaning_and_unit_equivalence():
    actual = convert_condition_values(["shaft_speed_rpm", "radial_force_n"], [25, 1], input_units=["Hz", "kN"])
    np.testing.assert_equal(actual, [1500, 1000])
    with pytest.raises(ValueError):
        convert_condition_values(["radial_force_n"], [1], input_units=["Nm"])


def test_training_query_executes_exported_coordinates_and_preserves_lora_gradients():
    torch.manual_seed(42)
    model = UnifiedSignalGenerator(num_faults=5, num_fault_groups=5, condition_dimension=2, num_devices=1,
                                   base_channels=8, context_dimension=32, attention_heads=4,
                                   style_attention_rank=4, style_token_count=2, lora_rank=8)
    with torch.no_grad():
        model.style_field.query.lora_up.normal_(std=0.01)
    mean, deviation = np.asarray([1500, 700], dtype=np.float32), np.asarray([1, 300], dtype=np.float32)
    original_names = set(model.state_dict())
    query = FoldedTrainingQuery(model.style_field.query, mean, deviation)
    model.style_field.query = query
    folded = folded_device_lora(model, 0, mean, deviation)
    inputs = torch.tensor([[1., 900., 1000.], [1., 1500., 400.]])
    routes = torch.zeros(2, dtype=torch.long)
    actual = query(inputs, routes)
    down = folded["style_field.query.lora_down"]
    up = folded["style_field.query.lora_up"]
    latent = torch.einsum("bi,bri->br", inputs, down[None].expand(2, -1, -1))
    expected = query.shared(inputs) + torch.einsum("br,bor->bo", latent, up[None].expand(2, -1, -1)) / query.rank
    torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    actual.square().mean().backward()
    assert torch.isfinite(query.lora_up.grad).all() and query.lora_up.grad.abs().sum() > 0
    assert torch.isfinite(query.lora_down.grad).all() and query.lora_down.grad.abs().sum() > 0
    assert set(model.state_dict()) == original_names


def test_frozen_semantic_tokens_and_no_target_records(release):
    value = validate_manifest(manifest(), release)
    assert value["fault_tokens"] == {"normal": {"fault_index": 4, "fault_group_index": 2}}
    value["records"][1]["split"] = "test"
    with pytest.raises(ValueError, match="测试"):
        validate_manifest(value, release)


@pytest.mark.parametrize("mutation", ["path", "duplicate_record", "duplicate_file", "missing_cell", "unknown_fault", "negative_force"])
def test_rejects_unusable_upload_before_creating_job(release, mutation):
    value = manifest()
    if mutation == "path":
        value["records"][0]["file"] = "../train.npy"
    elif mutation == "duplicate_record":
        value["records"][1]["record_id"] = "train"
    elif mutation == "duplicate_file":
        value["records"][1]["file"] = "train.npy"
    elif mutation == "missing_cell":
        value["records"][1]["conditions"]["radial_force_n"] = 400
    elif mutation == "unknown_fault":
        value["records"][0]["fault"] = "unknown"
    else:
        value["records"][0]["conditions"]["radial_force_n"] = -1
    with pytest.raises(ValueError):
        validate_manifest(value, release)


def test_signal_reader_does_not_mix_channels_or_accept_nan(tmp_path):
    path = tmp_path / "signal.npy"
    np.save(path, np.ones((2, 16384), dtype=np.float32))
    with pytest.raises(ValueError, match="单通道"):
        read_signal(path, channel="vibration")
    signal = np.ones(16384, dtype=np.float32)
    signal[12] = np.nan
    np.save(path, signal)
    with pytest.raises(ValueError, match="有限"):
        read_signal(path, channel="vibration")


def test_upload_detects_content_leakage_and_becomes_immutable_after_validation(tmp_path, release):
    recipe = json.loads((PROJECT / "faultcrafter/resources/device_lora_training_v1.json").read_text(encoding="utf-8"))
    manager = DeviceOnboarding(release, tmp_path, recipe)
    created = manager.create(manifest())
    job_id = created["job_id"]
    buffer = io.BytesIO()
    np.save(buffer, np.arange(16384, dtype=np.float32))
    for filename in ("train.npy", "validation.npy"):
        manager.upload(job_id, filename, io.BytesIO(buffer.getvalue()), len(buffer.getvalue()))
    with pytest.raises(ValueError, match="同一信号"):
        manager.validate(job_id)
    np.save(manager.job_root(job_id) / "uploads/validation.npy", np.arange(16384, dtype=np.float32) + 0.5)
    assert manager.validate(job_id)["state"] == "validated"
    with pytest.raises(ValueError, match="校验后"):
        manager.upload(job_id, "train.npy", io.BytesIO(buffer.getvalue()), len(buffer.getvalue()))


def test_external_device_registration_keeps_release_immutable(tmp_path, release):
    import shutil

    original = CompactDeploymentManifest.load(release)
    source = release / "bjtu_rao_bogie"
    installed = tmp_path / "uploaded_rig"
    installed.mkdir()
    profile = json.loads((source / "signal_profile.json").read_text(encoding="utf-8"))
    profile["device_id"] = "uploaded_rig"
    profile["fixed_conditions"] = {"shaft_torque_nm": 0.7}
    write_json(installed / "signal_profile.json", profile)
    shutil.copyfile(source / "device_lora.pt", installed / "device_lora.pt")
    expanded = CompactDeploymentManifest.load(release, extra_device_root=tmp_path)
    assert len(expanded.devices) == len(original.devices) + 1
    assert expanded.device_roots["uploaded_rig"] == installed
    assert expanded.raw["shared_sha256"] == original.raw["shared_sha256"]
    assert expanded.raw["devices"][-1]["fixed_conditions"] == {"shaft_torque_nm": 0.7}
