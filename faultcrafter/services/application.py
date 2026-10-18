from __future__ import annotations

import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import threading
from typing import Any

from faultcrafter.compact_deployment import CompactDeploymentManifest, CompactJiTRuntime
from faultcrafter.condition_units import UNIT_PROTOCOL, unit_control_metadata
from faultcrafter.signal_analysis import analyze_signal
from faultcrafter.typed_conditions import prepare_condition_request
from faultcrafter.services.batch_generation import (
    MAXIMUM_BATCH_POINTS, MAXIMUM_BATCH_SAMPLES, MAXIMUM_CONDITION_ROWS, BatchJobManager,
)
from faultcrafter.services.device_onboarding import DeviceOnboarding
from faultcrafter.services.model_defaults import (
    EXPERIMENT32_MODEL_ID, EXPERIMENT32_MODEL_LABEL, EXPERIMENT32_MODEL_SCOPE,
)
from faultcrafter.services.paths import default_data_root, default_model_root, package_root
from faultcrafter.services.locking import ComputeLock


class RuntimeApplication:
    def __init__(self, compact_root: Path | None = None, *, compute_device: str | None = None,
                 user_data_root: Path | None = None, onboarding_recipe: dict[str, Any] | None = None) -> None:
        default_root = default_model_root()
        configured_root = compact_root or os.environ.get("FAULTCRAFTER_MODEL_ROOT") or default_root
        self.compact_root = Path(configured_root).expanduser().resolve()
        if not (self.compact_root / "shared_generator.pt").is_file():
            raise FileNotFoundError(
                f"模型包不存在: {self.compact_root}. 请使用 --model-root 或 FAULTCRAFTER_MODEL_ROOT 指向发布包。"
            )
        self.compute_device = compute_device
        self.manifest = CompactDeploymentManifest.load(self.compact_root)
        if self.compact_root == default_root.resolve():
            if self.manifest.raw.get("release_id") != EXPERIMENT32_MODEL_ID:
                raise ValueError("default model must be the experiment32 full-data release, not a benchmark fold")
        configured_data = user_data_root or os.environ.get("FAULTCRAFTER_DATA_ROOT")
        self.user_data_root = Path(configured_data or default_data_root()).expanduser().resolve()
        if configured_data is None and self.manifest.raw.get("release_id") != EXPERIMENT32_MODEL_ID:
            self.user_data_root = self.user_data_root / "model_state" / self.manifest.raw["shared_sha256"]
        if (self.user_data_root / "devices").is_dir():
            self.manifest = CompactDeploymentManifest.load(
                self.compact_root, extra_device_root=self.user_data_root / "devices"
            )
        self._compute_lock = ComputeLock(self.user_data_root / "runtime.lock")
        if self.manifest.raw.get("release_id") == EXPERIMENT32_MODEL_ID:
            self.manifest = replace(
                self.manifest, model_id=EXPERIMENT32_MODEL_ID, model_label=EXPERIMENT32_MODEL_LABEL,
                raw={**self.manifest.raw, "model_id": EXPERIMENT32_MODEL_ID,
                     "model_label": EXPERIMENT32_MODEL_LABEL, "model_scope": EXPERIMENT32_MODEL_SCOPE},
            )
        self._runtime: CompactJiTRuntime | None = None
        self._runtime_lock = threading.Lock()
        self._onboarding_lock = threading.Lock()
        self._onboarding_recipe = onboarding_recipe
        self.onboarding_available = self.manifest.raw.get("release_id") == EXPERIMENT32_MODEL_ID
        self.onboarding: DeviceOnboarding | None = None
        self.batch_jobs = BatchJobManager(self.manifest, self.runtime)

    def refresh_devices(self) -> None:
        with self._runtime_lock:
            updated = CompactDeploymentManifest.load(self.compact_root, extra_device_root=self.user_data_root / "devices")
            self.manifest = replace(updated, model_id=self.manifest.model_id, model_label=self.manifest.model_label,
                raw={**updated.raw, **{name: self.manifest.raw[name] for name in ("model_id", "model_label", "model_scope")}})
            self._runtime = None
            self.batch_jobs.manifest = self.manifest

    def device_jobs(self) -> DeviceOnboarding:
        if not self.onboarding_available:
            raise ValueError("新设备训练需要32全数据发布主干")
        with self._onboarding_lock:
            if self.onboarding is None:
                recipe = self._onboarding_recipe or json.loads(
                    (package_root() / "resources/device_lora_training_v1.json").read_text(encoding="utf-8")
                )
                self.onboarding = DeviceOnboarding(
                    self.compact_root, self.user_data_root, recipe,
                    compute_device=self.compute_device, on_registered=self.refresh_devices,
                    compute_lock=self._compute_lock,
                )
        return self.onboarding

    def runtime(self) -> CompactJiTRuntime:
        with self._runtime_lock:
            if self._runtime is None:
                self._runtime = CompactJiTRuntime(self.manifest, device=self.compute_device, compute_lock=self._compute_lock)
            return self._runtime

    def public_manifest(self) -> dict[str, Any]:
        raw = self.manifest.raw
        devices = copy.deepcopy(raw["devices"])
        for route in devices:
            for control in route["parameters"]:
                control.update(unit_control_metadata(control["name"]))
        return {
            "model_id": raw["model_id"],
            "device_onboarding_available": self.onboarding_available,
            "model_label": raw["model_label"],
            "shared_sha256": raw.get("shared_sha256"),
            "device_lora_rank": raw["device_lora_rank"],
            "devices": devices,
            "runtime": raw["runtime"],
            "training_lengths": raw["selection"]["training_lengths"],
            "condition_unit_protocol": UNIT_PROTOCOL,
            "condition_model_protocol": raw.get("condition_model_protocol"),
            "runtime_contract": raw.get("runtime_contract", "legacy_deployment"),
            "model_scope": raw.get("model_scope", "用户指定的紧凑模型包。"),
            "batch_limits": {
                "maximum_samples": MAXIMUM_BATCH_SAMPLES,
                "maximum_points": MAXIMUM_BATCH_POINTS,
                "maximum_condition_rows": MAXIMUM_CONDITION_ROWS,
            },
        }

    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.onboarding is not None and self.onboarding.has_active_job():
            raise ValueError("设备正在训练，请完成后生成信号")
        requested_route = self.manifest.device(str(payload["device_id"]))
        parameters, conversion = prepare_condition_request(
            requested_route.parameter_names, dict(payload["condition_parameters"]),
            input_units=payload.get("condition_units"),
            model_protocol=self.manifest.raw.get("condition_model_protocol"),
        )
        result = self.runtime().generate(
            device_id=str(payload["device_id"]),
            fault_id=str(payload["fault_id"]),
            condition_parameters=parameters,
            length=int(payload["length"]),
            seed=int(payload["seed"]),
        )
        route = next(
            item for item in self.manifest.raw["devices"] if item["id"] == result.device_id
        )
        analysis = analyze_signal(
            result.physical_signal,
            result.sample_rate_hz,
            fault_id=result.fault_id,
            condition_parameters=result.condition_parameters,
            bearing_diagnostics=route.get("bearing_diagnostics"),
            maximum_frequency_hz=float(
                route.get("bearing_diagnostics", {}).get("maximum_frequency_hz", 2_000)
            ),
        )
        return {
            "model_id": self.manifest.model_id,
            "shared_sha256": self.manifest.raw["shared_sha256"],
            "normalized_signal": result.normalized_signal.tolist(),
            "physical_signal": result.physical_signal.tolist(),
            "predicted_amplitude": result.predicted_amplitude,
            "sample_rate_hz": result.sample_rate_hz,
            "physical_unit": result.physical_unit,
            "device_id": result.device_id,
            "fault_id": result.fault_id,
            "condition_parameters": result.condition_parameters,
            "condition_conversion": conversion,
            "seed": result.seed,
            "elapsed_seconds": result.elapsed_seconds,
            "compute_device": result.compute_device,
            "fixed_conditions": route.get("fixed_conditions", {}),
            "analysis": analysis,
        }

    def start_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.onboarding is not None and self.onboarding.has_active_job():
            raise ValueError("设备正在训练，请完成后批量生成")
        return self.batch_jobs.start(payload)
