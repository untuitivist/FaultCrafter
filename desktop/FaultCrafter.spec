import os
from pathlib import Path
import runpy
import torch
from PyInstaller.utils.hooks import collect_data_files


project_root = Path(SPECPATH).resolve().parent
build_variant = os.environ.get("FAULTCRAFTER_BUILD_VARIANT", "gpu").lower()
if build_variant not in {"gpu", "cpu", "cpu_batch"}:
    raise ValueError(f"unknown build variant: {build_variant}")
application_name = {
    "gpu": "FaultCrafter-JiT-4Device-Web",
    "cpu": "FaultCrafter-JiT-4Device-Web-CPU-Analysis",
    "cpu_batch": "FaultCrafter-JiT-4Device-Web-CPU-Batch",
}[build_variant]
model_defaults = runpy.run_path(str(project_root / "faultcrafter/services/model_defaults.py"))
compact_root = Path(os.environ.get("FAULTCRAFTER_MODEL_ROOT", str(project_root / model_defaults["EXPERIMENT32_COMPACT_PATH"])))
checkpoint = compact_root / "shared_generator.pt"
web_assets = project_root / "faultcrafter/gui/assets"
web_page = web_assets / "faultcrafter-jit-deployment.html"
web_script = web_assets / "deployment-app.js"
unit_script = web_assets / "condition-units.js"
if not checkpoint.is_file():
    raise FileNotFoundError(f"formal checkpoint is missing: {checkpoint}")
shared = torch.load(checkpoint, map_location="cpu", weights_only=True)
if shared.get("release_id") != model_defaults["EXPERIMENT32_MODEL_ID"]:
    raise ValueError("Web build requires the experiment32 full-data release, not a benchmark fold")
profiles = sorted(compact_root.glob("*/signal_profile.json"))
if len(profiles) != 4:
    raise ValueError("experiment32 Web build requires all four device identities")
model_assets = [(str(checkpoint), "assets/compact")]
for profile in profiles:
    adapter = profile.parent / "device_lora.pt"
    if not adapter.is_file():
        raise FileNotFoundError(f"experiment32 device LoRA is missing: {adapter}")
    destination = f"assets/compact/{profile.parent.name}"
    model_assets.extend([(str(profile), destination), (str(adapter), destination)])
if not web_page.is_file() or not web_script.is_file() or not unit_script.is_file():
    raise FileNotFoundError("deployment Web assets are missing")


analysis = Analysis(
    [str(project_root / "desktop" / "web_server.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=model_assets + collect_data_files("faultcrafter", includes=["gui/assets/*", "resources/*.json"]),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "fastapi",
        "matplotlib",
        "pandas",
        "PIL",
        "uvicorn",
        "paddle",
        "cv2",
        "imageio",
        "imageio_ffmpeg",
        "pyarrow",
        "transformers",
        "torchvision",
        "torchaudio",
        "ray",
        "plotly",
        "onnx",
        "onnxruntime",
        "google.genai",
        "grpc",
        "jedi",
        "IPython",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=application_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=application_name,
)
