from __future__ import annotations

import csv
import io
from pathlib import Path
import time
from types import SimpleNamespace
import zipfile

import numpy as np

from faultcrafter.services import batch_generation
from faultcrafter.services.batch_generation import BatchJobManager
from faultcrafter.unified_jit_deployment import (
    UnifiedDeploymentManifest,
    UnifiedGenerationResult,
)


def manifest() -> UnifiedDeploymentManifest:
    devices = []
    for index in range(4):
        devices.append(
            {
                "index": index,
                "id": f"device_{index}",
                "label": f"device {index}",
                "sensor_label": "sensor",
                "channel": "channel",
                "quantity_label": "signal",
                "physical_unit": "unit",
                "sample_rate_hz": 1_000,
                "faults": [
                    {
                        "id": fault_id,
                        "label": fault_id,
                        "group": fault_id,
                        "global_index": index * 2 + fault_index,
                    }
                    for fault_index, fault_id in enumerate(("fault_a", "fault_b"))
                ],
                "parameters": [
                    {
                        "name": "shaft_speed_rpm",
                        "label": "speed",
                        "unit": "rpm",
                        "minimum": 100,
                        "maximum": 1_000,
                        "step": 1,
                        "initial": 600,
                        "measured": [600],
                    },
                    {
                        "name": "load_hp",
                        "label": "load",
                        "unit": "hp",
                        "minimum": 0,
                        "maximum": 5,
                        "step": 1,
                        "initial": 2,
                        "measured": [2],
                    },
                ],
                "parameter_mean": [600, 2],
                "parameter_standard_deviation": [100, 1],
                "speed_parameter_index": 0,
                "speed_to_hz": 1 / 60,
            }
        )
    return UnifiedDeploymentManifest.from_dict(
        {
            "schema_version": 2,
            "model_id": "test",
            "model_label": "test",
            "checkpoint_asset": "model.pt",
            "checkpoint_sha256": "0" * 64,
            "condition_dimension": 2,
            "devices": devices,
            "runtime": {
                "minimum_length": 64,
                "maximum_length": 256,
                "default_length": 128,
            },
            "architecture": {},
        }
    )


class FakeRuntime:
    compute_device = "cpu"

    def __init__(self) -> None:
        self.calls: list[tuple[int, ...]] = []

    def generate_many(self, **request: object) -> tuple[UnifiedGenerationResult, ...]:
        seeds = tuple(request["seeds"])
        self.calls.append(seeds)
        length = int(request["length"])
        parameters = dict(request["condition_parameters"])
        fault_id = str(request["fault_id"])
        return tuple(
            UnifiedGenerationResult(
                normalized_signal=np.linspace(-1, 1, length, dtype=np.float32),
                physical_signal=np.linspace(-2, 2, length, dtype=np.float32),
                predicted_amplitude=2.0,
                sample_rate_hz=1_000,
                physical_unit="unit",
                device_id="device_0",
                fault_id=fault_id,
                condition_parameters=parameters,
                seed=seed,
                elapsed_seconds=0.01,
                compute_device="cpu",
            )
            for seed in seeds
        )


def test_batch_job_generates_zip_manifest_and_signal_csvs(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "batch"
    output.mkdir()
    monkeypatch.setattr(
        batch_generation.tempfile, "mkdtemp", lambda prefix: str(output)
    )
    runtime = FakeRuntime()
    manager = BatchJobManager(manifest(), lambda: runtime)
    started = manager.start(
        {
            "device_id": "device_0",
            "fault_ids": ["fault_a", "fault_b"],
            "conditions": [
                {
                    "condition_parameters": {
                        "shaft_speed_rpm": 600,
                        "load_hp": 2,
                    },
                    "length": 64,
                    "count": 2,
                },
                {
                    "condition_parameters": {
                        "shaft_speed_rpm": 900,
                        "load_hp": 3,
                    },
                    "length": 128,
                    "count": 1,
                },
            ],
        }
    )
    deadline = time.monotonic() + 5
    status = manager.status(started["job_id"])
    while status["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)
        status = manager.status(started["job_id"])
    assert status["status"] == "completed", status
    assert status["completed_samples"] == 6
    archive_path, _ = manager.archive(started["job_id"])
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        signal_names = [name for name in names if name.startswith("signals/")]
        assert len(signal_names) == 6
        assert {"manifest.csv", "batch_config.json"}.issubset(names)
        manifest_text = archive.read("manifest.csv").decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(manifest_text)))
        assert len(rows) == 6
        assert {row["fault_id"] for row in rows} == {"fault_a", "fault_b"}
        assert {row["condition_label"] for row in rows} == {
            "600rpm_2hp_64pt_n2",
            "900rpm_3hp_128pt_n1",
        }
        signal_header = archive.read(signal_names[0]).decode("utf-8-sig").splitlines()[0]
        assert signal_header == (
            "sample_index,time_seconds,normalized_signal,physical_signal"
        )
    assert runtime.calls


def test_batch_job_rejects_excessive_total_points() -> None:
    runtime = SimpleNamespace()
    manager = BatchJobManager(manifest(), lambda: runtime)
    try:
        manager.start(
            {
                "device_id": "device_0",
                "fault_ids": ["fault_a", "fault_b"],
                "conditions": [
                    {
                        "condition_parameters": {
                            "shaft_speed_rpm": 600,
                            "load_hp": 2,
                        },
                        "length": 256,
                        "count": 1_000,
                    }
                    for _ in range(40)
                ],
            }
        )
    except ValueError as error:
        assert "batch sample total exceeds" in str(error)
    else:
        raise AssertionError("oversized batch was accepted")
