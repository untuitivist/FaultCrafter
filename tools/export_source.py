from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


ROOT_FILES = ("README.md", "LICENSE", "pyproject.toml", ".gitignore", ".gitattributes")
DOCUMENTS = ("docs/architecture.md", "docs/usage.md", "docs/development.md", "desktop/README_zh.md")
PATTERNS = {
    "faultcrafter": ("*.py",),
    "faultcrafter/gui/assets": ("*.html", "*.js"),
    "faultcrafter/resources": ("*.json",),
    "tests": ("*.py", "*.cjs"),
    "examples": ("*.json",),
    "desktop": ("*.py", "*.cmd", "*.spec", "requirements-build*.txt"),
}
BLOCKED_PARTS = frozenset({
    "__pycache__", ".git", ".agents", ".codex", "node_modules", ".venv", "research",
    "archives", "deliverables", "references", "third_party", "outputs", "results", "user_data",
})
MAXIMUM_FILE_BYTES = 5 * 1024 * 1024


def source_files(root: Path) -> list[Path]:
    selected = {root / name for name in (*ROOT_FILES, *DOCUMENTS, "tools/export_source.py")}
    for directory, patterns in PATTERNS.items():
        for pattern in patterns:
            paths = (root / directory).rglob(pattern) if directory == "faultcrafter" else (root / directory).glob(pattern)
            selected.update(path for path in paths if path.is_file())
    verified = []
    for path in sorted(selected):
        relative = path.relative_to(root)
        if BLOCKED_PARTS.intersection(relative.parts):
            continue
        if not path.is_file():
            raise FileNotFoundError(f"Required source file is missing: {relative}")
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent):
            raise ValueError(f"Symbolic links are not exported: {relative}")
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Source leaves repository: {relative}")
        if path.stat().st_size > MAXIMUM_FILE_BYTES:
            raise ValueError(f"Source file exceeds export limit: {relative}")
        path.read_text(encoding="utf-8-sig")
        verified.append(path)
    return verified


def export_source(root: Path, destination: Path) -> dict:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists() and (not destination.is_dir() or any(path.name != ".git" for path in destination.iterdir())):
        raise FileExistsError(f"Destination must be new or an empty Git checkout: {destination}")
    if destination.is_relative_to(root):
        raise ValueError("Export destination must be outside the research repository")
    selected = source_files(root)
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for source in selected:
        relative = source.relative_to(root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        observed = hashlib.sha256(target.read_bytes()).hexdigest()
        if observed != expected:
            raise RuntimeError(f"Export hash mismatch: {relative}")
        records.append({"path": relative.as_posix(), "bytes": target.stat().st_size, "sha256": observed})
    audit = {"schema": "faultcrafter_public_source_v1", "files": records,
             "file_count": len(records), "total_bytes": sum(record["bytes"] for record in records)}
    (destination / ".source-manifest.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8"
    )
    return audit


def main() -> None:
    arguments = argparse.ArgumentParser(description="Export the reviewed code-only GitHub surface")
    arguments.add_argument("--destination", type=Path, required=True)
    options = arguments.parse_args()
    report = export_source(Path(__file__).resolve().parents[1], options.destination)
    print(json.dumps({"destination": str(options.destination.resolve()), "files": report["file_count"],
                      "bytes": report["total_bytes"]}))


if __name__ == "__main__":
    main()
