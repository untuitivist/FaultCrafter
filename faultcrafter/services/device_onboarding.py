from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import threading
import traceback
from typing import Any, BinaryIO, Callable
import uuid
import zipfile

from faultcrafter.device_onboarding import MAXIMUM_UPLOAD_BYTES, identifier, sha256_file, validate_manifest, write_json


class DeviceOnboarding:
    def __init__(self, compact_root: Path, storage_root: Path, recipe: dict[str, Any], *,
                 compute_device: str | None = None, on_registered: Callable[[], None] | None = None,
                 compute_lock: threading.Lock | None = None) -> None:
        self.compact_root = compact_root
        self.root = storage_root
        self.recipe = copy.deepcopy(recipe)
        self.compute_device = compute_device
        self.on_registered = on_registered
        self.compute_lock = compute_lock or threading.Lock()
        self.devices_root = storage_root / "devices"
        self.jobs_root = storage_root / "jobs"
        self._lock = threading.RLock()
        self._active: str | None = None
        self._finished: dict[str, threading.Event] = {}
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.devices_root.mkdir(parents=True, exist_ok=True)

    def has_active_job(self) -> bool:
        with self._lock:
            return self._active is not None

    def job_root(self, job_id: str) -> Path:
        identifier(job_id)
        root = self.jobs_root / job_id
        if not root.is_dir():
            raise ValueError("训练任务不存在")
        return root

    def status(self, job_id: str, *, wait: float = 0) -> dict[str, Any]:
        root = self.job_root(job_id)
        with self._lock:
            event = self._finished.get(job_id)
        if event is not None and wait:
            event.wait(min(60, max(0, wait)))
        return json.loads((root / "status.json").read_text(encoding="utf-8"))

    def list_jobs(self) -> list[dict[str, Any]]:
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(self.jobs_root.glob("*/status.json"))]

    def wait(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            event = self._finished.get(job_id)
        if event is None:
            raise ValueError("只能等待当前进程启动的训练任务")
        event.wait()
        return self.status(job_id)

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            root = self.job_root(job_id)
            status = json.loads((root / "status.json").read_text(encoding="utf-8"))
            write_json(root / "status.json", {**status, **changes})

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        manifest = validate_manifest(payload, self.compact_root)
        device_id = manifest["device_id"]
        with self._lock:
            if (self.devices_root / device_id).exists() or (self.compact_root / device_id).exists():
                raise ValueError("设备标识已存在，请使用新的名称；不会覆盖已发布设备")
            if any(job["device_id"] == device_id and job["state"] not in ("failed", "interrupted") for job in self.list_jobs()):
                raise ValueError("这个设备已有任务，请继续原任务或使用新的名称")
            job_id = uuid.uuid4().hex
            root = self.jobs_root / job_id
            (root / "uploads").mkdir(parents=True)
            write_json(root / "manifest.json", manifest)
            write_json(root / "recipe.json", self.recipe)
            write_json(root / "status.json", {"job_id": job_id, "device_id": device_id, "state": "uploading",
                       "uploaded_files": [], "expected_files": len(manifest["records"]), "step": 0,
                       "maximum_steps": self.recipe["maximum_steps"], "shared_sha256": sha256_file(self.compact_root / "shared_generator.pt")})
        return self.status(job_id)

    def upload(self, job_id: str, filename: str, stream: BinaryIO, size: int) -> dict[str, Any]:
        if not 0 < size <= MAXIMUM_UPLOAD_BYTES:
            raise ValueError("单文件大小须为1字节到128MiB")
        with self._lock:
            root = self.job_root(job_id)
            if self.status(job_id)["state"] != "uploading":
                raise ValueError("校验后不能修改上传数据")
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            if filename not in {row["file"] for row in manifest["records"]}:
                raise ValueError("文件不在任务清单中")
            path = root / "uploads" / filename
            if path.exists():
                raise ValueError("文件已上传，不允许覆盖")
            temporary = root / f"upload_{uuid.uuid4().hex}.partial"
            remaining = size
            with temporary.open("xb") as output:
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("上传被中断，原有数据保持不变")
                    output.write(block)
                    remaining -= len(block)
            temporary.rename(path)
            uploaded = sorted(value.name for value in (root / "uploads").iterdir())
            self._update(job_id, uploaded_files=uploaded)
        return {"job_id": job_id, "uploaded": filename, "received_files": len(uploaded)}

    def validate(self, job_id: str) -> dict[str, Any]:
        from faultcrafter.device_lora_training import UploadedCorpus

        with self._lock:
            root = self.job_root(job_id)
            status = self.status(job_id)
            if status["state"] != "uploading":
                raise ValueError("只有上传中的任务可以校验")
            if len(status["uploaded_files"]) != status["expected_files"]:
                raise ValueError("还有清单文件未上传")
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            corpus = UploadedCorpus(root, manifest)
            write_json(root / "upload_audit.json", {"records": corpus.audit,
                       "manifest_sha256": sha256_file(root / "manifest.json"), "recipe_sha256": sha256_file(root / "recipe.json")})
            self._update(job_id, state="validated", validation={"records": len(corpus.rows),
                         "train_records": sum(row["split"] == "train" for row in corpus.rows),
                         "validation_records": sum(row["split"] == "validation" for row in corpus.rows),
                         "faults": list(manifest["fault_tokens"]), "fixed_conditions": manifest["fixed_conditions"]})
        return self.status(job_id)

    def start(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if self._active is not None:
                raise ValueError("当前已有设备训练；每次只训练一个设备")
            if self.status(job_id)["state"] != "validated":
                raise ValueError("请先完成文件校验")
            self._active = job_id
            self._finished[job_id] = threading.Event()
            self._update(job_id, state="training")
            threading.Thread(target=self._train, args=(job_id,), daemon=True, name=f"device-{job_id}").start()
        return self.status(job_id)

    def _train(self, job_id: str) -> None:
        root = self.job_root(job_id)
        try:
            from faultcrafter.device_lora_training import train_device_lora

            audit = json.loads((root / "upload_audit.json").read_text(encoding="utf-8"))
            if self.status(job_id)["shared_sha256"] != sha256_file(self.compact_root / "shared_generator.pt"):
                raise RuntimeError("任务创建后共享发布主干发生变化")
            if audit["manifest_sha256"] != sha256_file(root / "manifest.json") or audit["recipe_sha256"] != sha256_file(root / "recipe.json"):
                raise RuntimeError("校验后训练清单发生变化")
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            rows = {row["record_id"]: row for row in manifest["records"]}
            for record in audit["records"]:
                if sha256_file(root / "uploads" / rows[record["record_id"]]["file"]) != record["file_sha256"]:
                    raise RuntimeError("校验后上传信号发生变化")
            recipe = json.loads((root / "recipe.json").read_text(encoding="utf-8"))
            with self.compute_lock:
                output = train_device_lora(root, self.compact_root, recipe, compute_device=self.compute_device,
                                          progress=lambda row: self._update(job_id, **row))
            device_root = self.devices_root / manifest["device_id"]
            if device_root.exists():
                raise ValueError("注册目标已存在，不覆盖已有设备")
            staging = root / "registration"
            shutil.copytree(output, staging)
            staging.rename(device_root)
            if self.on_registered:
                self.on_registered()
            self._update(job_id, state="ready", device_id=manifest["device_id"],
                         download_url=f"/api/devices/download?job_id={job_id}",
                         training_audit=json.loads((root / "training_audit.json").read_text(encoding="utf-8")),
                         export_audit=json.loads((root / "export_audit.json").read_text(encoding="utf-8")))
        except Exception as error:
            with (root / "training.log").open("a", encoding="utf-8") as stream:
                stream.write(traceback.format_exc())
            self._update(job_id, state="failed", error=str(error))
        finally:
            with self._lock:
                self._active = None
                self._finished[job_id].set()

    def archive(self, job_id: str) -> tuple[Path, str]:
        root = self.job_root(job_id)
        status = self.status(job_id)
        if status["state"] != "ready":
            raise ValueError("设备尚未通过训练和导出校验")
        path = root / "device_package.zip"
        with self._lock:
            if not path.exists():
                with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.write(self.compact_root / "shared_generator.pt", "shared_generator.pt")
                    for name in ("device_lora.pt", "signal_profile.json"):
                        archive.write(self.devices_root / status["device_id"] / name, f"{status['device_id']}/{name}")
        return path, f"{status['device_id']}.zip"
