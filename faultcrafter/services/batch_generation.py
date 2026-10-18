from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
import io
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
from typing import Any, Callable, Mapping
from uuid import uuid4
import zipfile

import numpy as np
from faultcrafter.typed_conditions import prepare_condition_request

from faultcrafter.unified_jit_deployment import (
    DeviceControl,
    UnifiedDeploymentManifest,
    UnifiedGenerationResult,
    UnifiedJiTRuntime,
)


MAXIMUM_BATCH_SAMPLES = 2_000
MAXIMUM_BATCH_POINTS = 20_000_000
MAXIMUM_CONDITION_ROWS = 100
POINT_BUDGET_PER_INFERENCE = 131_072


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def condition_label(
    route: DeviceControl,
    parameters: Mapping[str, float],
    length: int,
    count: int,
) -> str:
    parts = [
        f"{_format_number(float(parameters[control.name]))}{control.unit}"
        for control in route.parameters
    ]
    parts.extend((f"{length}pt", f"n{count}"))
    return "_".join(parts)


@dataclass(frozen=True, slots=True)
class BatchCondition:
    label: str
    parameters: Mapping[str, float]
    length: int
    count: int
    unit_conversion: Mapping[str, Any] | None = None


@dataclass(slots=True)
class BatchJob:
    id: str
    device_id: str
    fault_ids: tuple[str, ...]
    conditions: tuple[BatchCondition, ...]
    total_samples: int
    total_points: int
    base_seed: int
    status: str = "queued"
    completed_samples: int = 0
    current_label: str = ""
    current_fault_id: str = ""
    error: str | None = None
    archive_path: Path | None = None
    archive_name: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    finished: threading.Event = field(default_factory=threading.Event, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            now = self.completed_at or time.time()
            origin = self.started_at or self.created_at
            elapsed = max(0.0, now - origin)
            eta = None
            if self.status == "running" and self.completed_samples:
                eta = elapsed / self.completed_samples * (
                    self.total_samples - self.completed_samples
                )
            return {
                "job_id": self.id,
                "status": self.status,
                "device_id": self.device_id,
                "total_samples": self.total_samples,
                "total_points": self.total_points,
                "completed_samples": self.completed_samples,
                "progress": self.completed_samples / self.total_samples,
                "current_label": self.current_label,
                "current_fault_id": self.current_fault_id,
                "elapsed_seconds": elapsed,
                "eta_seconds": eta,
                "error": self.error,
                "download_ready": self.status == "completed",
                "archive_name": self.archive_name,
            }


class BatchJobManager:
    def __init__(
        self,
        manifest: UnifiedDeploymentManifest,
        runtime: Callable[[], UnifiedJiTRuntime],
    ) -> None:
        self.manifest = manifest
        self._runtime = runtime
        self._jobs: dict[str, BatchJob] = {}
        self._manager_lock = threading.Lock()

    def wait(self, job_id: str) -> dict[str, Any]:
        with self._manager_lock:
            job = self._jobs[job_id]
        job.finished.wait()
        return job.snapshot()

    def _validated_conditions(
        self, route: DeviceControl, values: Any
    ) -> tuple[BatchCondition, ...]:
        if not isinstance(values, list) or not 1 <= len(values) <= MAXIMUM_CONDITION_ROWS:
            raise ValueError(
                f"condition rows must contain between 1 and {MAXIMUM_CONDITION_ROWS} items"
            )
        minimum_length = int(self.manifest.runtime["minimum_length"])
        maximum_length = int(self.manifest.runtime["maximum_length"])
        rows = []
        for value in values:
            raw_parameters = dict(value["condition_parameters"])
            if set(raw_parameters) != set(route.parameter_names):
                raise ValueError("batch condition parameter names differ from the device route")
            parameters, conversion = prepare_condition_request(
                route.parameter_names, raw_parameters, input_units=value.get("condition_units"),
                model_protocol=self.manifest.raw.get("condition_model_protocol"),
            )
            for control in route.parameters:
                parameter = parameters[control.name]
                if not np.isfinite(parameter) or not control.minimum <= parameter <= control.maximum:
                    raise ValueError(
                        f"{control.label} must lie in [{control.minimum}, {control.maximum}] {control.unit}"
                    )
            length = int(value["length"])
            count = int(value["count"])
            if not minimum_length <= length <= maximum_length:
                raise ValueError(
                    f"signal length must lie in [{minimum_length}, {maximum_length}]"
                )
            if not 1 <= count <= 1_000:
                raise ValueError("sample count per fault must lie in [1, 1000]")
            rows.append(
                BatchCondition(
                    label=condition_label(route, parameters, length, count),
                    parameters=parameters,
                    unit_conversion=conversion,
                    length=length,
                    count=count,
                )
            )
        return tuple(rows)

    def start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        route = self.manifest.device(str(payload["device_id"]))
        raw_faults = payload["fault_ids"]
        if not isinstance(raw_faults, list) or not raw_faults:
            raise ValueError("at least one batch fault must be selected")
        fault_ids = tuple(dict.fromkeys(str(value) for value in raw_faults))
        unsupported = sorted(set(fault_ids) - set(route.fault_ids))
        if unsupported:
            raise ValueError(f"unsupported batch faults: {unsupported}")
        conditions = self._validated_conditions(route, payload["conditions"])
        total_samples = len(fault_ids) * sum(row.count for row in conditions)
        total_points = len(fault_ids) * sum(
            row.count * row.length for row in conditions
        )
        if total_samples > MAXIMUM_BATCH_SAMPLES:
            raise ValueError(
                f"batch sample total exceeds {MAXIMUM_BATCH_SAMPLES}: {total_samples}"
            )
        if total_points > MAXIMUM_BATCH_POINTS:
            raise ValueError(
                f"batch point total exceeds {MAXIMUM_BATCH_POINTS}: {total_points}"
            )
        with self._manager_lock:
            if any(job.status in {"queued", "running"} for job in self._jobs.values()):
                raise RuntimeError("another batch job is already running")
            job_id = uuid4().hex
            job = BatchJob(
                id=job_id,
                device_id=route.id,
                fault_ids=fault_ids,
                conditions=conditions,
                total_samples=total_samples,
                total_points=total_points,
                base_seed=secrets.randbelow(2_000_000_000 - total_samples),
            )
            self._jobs[job_id] = job
        threading.Thread(
            target=self._run,
            args=(job, route),
            name=f"faultcrafter-batch-{job_id[:8]}",
            daemon=True,
        ).start()
        return job.snapshot()

    def status(self, job_id: str) -> dict[str, Any]:
        try:
            job = self._jobs[job_id]
        except KeyError as error:
            raise ValueError("unknown batch job") from error
        return job.snapshot()

    def archive(self, job_id: str) -> tuple[Path, str]:
        try:
            job = self._jobs[job_id]
        except KeyError as error:
            raise ValueError("unknown batch job") from error
        with job.lock:
            if job.status != "completed" or job.archive_path is None or job.archive_name is None:
                raise RuntimeError("batch archive is not ready")
            return job.archive_path, job.archive_name

    def has_active_job(self) -> bool:
        with self._manager_lock:
            return any(job.status in {"queued", "running"} for job in self._jobs.values())

    def _run(self, job: BatchJob, route: DeviceControl) -> None:
        with job.lock:
            job.status = "running"
            job.started_at = time.time()
        try:
            output_root = Path(tempfile.mkdtemp(prefix="faultcrafter-batch-"))
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            archive_name = f"faultcrafter-{route.id}-{timestamp}.zip"
            archive_path = output_root / archive_name
            manifest_rows: list[dict[str, Any]] = []
            next_seed = job.base_seed
            with zipfile.ZipFile(
                archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                for row_index, condition in enumerate(job.conditions, start=1):
                    for fault_id in job.fault_ids:
                        remaining = condition.count
                        sample_index = 0
                        while remaining:
                            chunk_size = min(
                                remaining,
                                16,
                                max(1, POINT_BUDGET_PER_INFERENCE // condition.length),
                            )
                            seeds = tuple(range(next_seed, next_seed + chunk_size))
                            next_seed += chunk_size
                            with job.lock:
                                job.current_label = condition.label
                                job.current_fault_id = fault_id
                            results = self._runtime().generate_many(
                                device_id=route.id,
                                fault_id=fault_id,
                                condition_parameters=condition.parameters,
                                length=condition.length,
                                seeds=seeds,
                            )
                            for result in results:
                                sample_index += 1
                                sample_id = f"r{row_index:03d}_{fault_id}_{sample_index:04d}"
                                relative_path = (
                                    f"signals/{row_index:03d}_{condition.label}/"
                                    f"{fault_id}/{sample_index:04d}_seed_{result.seed}.csv"
                                )
                                archive.writestr(relative_path, self._signal_csv(result))
                                manifest_rows.append(
                                    self._manifest_row(
                                        sample_id,
                                        condition,
                                        route,
                                        result,
                                        relative_path,
                                    )
                                )
                                with job.lock:
                                    job.completed_samples += 1
                            remaining -= chunk_size
                archive.writestr(
                    "manifest.csv", self._manifest_csv(route, manifest_rows)
                )
                archive.writestr(
                    "batch_config.json",
                    json.dumps(
                        {
                            "schema_version": 1,
                            "model_id": self.manifest.model_id,
                            "device_id": route.id,
                            "sensor_label": route.sensor_label,
                            "channel": route.channel,
                            "fault_ids": job.fault_ids,
                            "base_seed": job.base_seed,
                            "total_samples": job.total_samples,
                            "total_points": job.total_points,
                            "conditions": [
                                {
                                    "label": row.label,
                                    "condition_parameters": row.parameters,
                                    "condition_conversion": row.unit_conversion,
                                    "length": row.length,
                                    "count_per_fault": row.count,
                                }
                                for row in job.conditions
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            with job.lock:
                job.status = "completed"
                job.completed_at = time.time()
                job.archive_path = archive_path
                job.archive_name = archive_name
                job.current_label = ""
                job.current_fault_id = ""
        except Exception as error:
            with job.lock:
                job.status = "failed"
                job.completed_at = time.time()
                job.error = str(error)
        finally:
            job.finished.set()

    @staticmethod
    def _signal_csv(result: UnifiedGenerationResult) -> str:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(
            ("sample_index", "time_seconds", "normalized_signal", "physical_signal")
        )
        for index, (normalized, physical) in enumerate(
            zip(result.normalized_signal, result.physical_signal, strict=True)
        ):
            writer.writerow(
                (
                    index,
                    f"{index / result.sample_rate_hz:.12g}",
                    f"{float(normalized):.9g}",
                    f"{float(physical):.9g}",
                )
            )
        return "\ufeff" + stream.getvalue()

    @staticmethod
    def _manifest_row(
        sample_id: str,
        condition: BatchCondition,
        route: DeviceControl,
        result: UnifiedGenerationResult,
        relative_path: str,
    ) -> dict[str, Any]:
        physical = result.physical_signal.astype(np.float64)
        row = {
            "sample_id": sample_id,
            "condition_label": condition.label,
            "device_id": route.id,
            "sensor_label": route.sensor_label,
            "channel": route.channel,
            "fault_id": result.fault_id,
            "length": len(physical),
            "seed": result.seed,
            "sample_rate_hz": result.sample_rate_hz,
            "physical_unit": result.physical_unit,
            "predicted_amplitude": result.predicted_amplitude,
            "rms": float(np.sqrt(np.mean(np.square(physical)))),
            "peak_to_peak": float(np.ptp(physical)),
            "csv_path": relative_path,
        }
        row.update(result.condition_parameters)
        return row

    @staticmethod
    def _manifest_csv(route: DeviceControl, rows: list[dict[str, Any]]) -> str:
        fields = [
            "sample_id",
            "condition_label",
            "device_id",
            "sensor_label",
            "channel",
            "fault_id",
            *route.parameter_names,
            "length",
            "seed",
            "sample_rate_hz",
            "physical_unit",
            "predicted_amplitude",
            "rms",
            "peak_to_peak",
            "csv_path",
        ]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
        return "\ufeff" + stream.getvalue()
