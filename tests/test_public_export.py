from pathlib import Path

from tools.export_source import source_files


def test_public_surface_contains_product_resources_and_excludes_private_material():
    root = Path(__file__).resolve().parents[1]
    paths = {path.relative_to(root).as_posix() for path in source_files(root)}
    assert "faultcrafter/gui/assets/device-onboarding.html" in paths
    assert "faultcrafter/resources/device_lora_training_v1.json" in paths
    assert "LICENSE" in paths
    assert not any(path.startswith(("research/", "deliverables/", "outputs/", "results/", "user_data/")) for path in paths)
    assert not {".NOTE.md", "task_plan.md", "progress.md", "findings.md", "AGENTS.md"} & paths
    assert not any(Path(path).suffix in {".tex", ".bib", ".pdf", ".pt", ".zip", ".npy", ".npz"} for path in paths)
