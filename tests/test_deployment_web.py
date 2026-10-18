from __future__ import annotations

import pytest

from faultcrafter.gui.server import WebApplication as RuntimeApplication
from faultcrafter.services.model_defaults import EXPERIMENT32_COMPACT_PATH, EXPERIMENT32_MODEL_ID


pytestmark = pytest.mark.skipif(not EXPERIMENT32_COMPACT_PATH.is_dir(), reason="Release weights are installed separately")


def test_deployment_page_exposes_all_analysis_views(tmp_path) -> None:
    application = RuntimeApplication(user_data_root=tmp_path)
    html = application.html.decode("utf-8")
    javascript = application.javascript.decode("utf-8")
    for label in ("时域", "频谱", "包络谱", "阶次谱", "时频图"):
        assert f'>{label}</button>' in html
    assert "信号真实性诊断" in html
    assert "drawSpectrogram" in javascript
    assert "diagnosticCharacteristic" in javascript


def test_web_unit_controls_share_the_backend_contract_and_preserve_numeric_input(tmp_path) -> None:
    application = RuntimeApplication(user_data_root=tmp_path)
    html = application.html.decode("utf-8")
    javascript = application.javascript.decode("utf-8")
    assert '<select class="condition-unit-select" id="frequency-unit"' in html
    assert '<select class="condition-unit-select" id="load-unit"' in html
    assert 'src="/condition-units.js"' in html
    assert 'id="unit-conversion-summary"' in html
    assert "condition_units: conditionUnits()" in javascript
    assert "condition_units: conditionUnitValues" in javascript
    assert "units.numeric(elements.firstNumber.value)" in javascript
    assert "unit_options" in application.public_manifest()["devices"][0]["parameters"][0]


def test_deployment_page_exposes_batch_generation_and_shutdown(tmp_path) -> None:
    application = RuntimeApplication(user_data_root=tmp_path)
    html = application.html.decode("utf-8")
    javascript = application.javascript.decode("utf-8")
    for marker in (
        'id="exit-button"',
        'id="batch-generation-panel"',
        'id="batch-condition-body"',
        'id="batch-start-button"',
    ):
        assert marker in html
    for endpoint in (
        "/api/batch/start",
        "/api/batch/status",
        "/api/batch/download",
        "/api/shutdown",
    ):
        assert endpoint in javascript
    assert "documentWidth" not in javascript


def test_public_manifest_includes_bjtu_bearing_diagnostics(tmp_path) -> None:
    application = RuntimeApplication(user_data_root=tmp_path)
    manifest = application.public_manifest()
    if EXPERIMENT32_COMPACT_PATH.exists():
        assert manifest["model_id"] == EXPERIMENT32_MODEL_ID
        assert manifest["shared_sha256"]
        assert manifest["runtime_contract"] == "shared_generator + current_device_lora + signal_profile"
    assert len(manifest["devices"]) == 4
    bjtu = next(item for item in manifest["devices"] if item["id"] == "bjtu_rao_bogie")
    diagnostics = bjtu["bearing_diagnostics"]
    assert diagnostics["bearing_model"] == "HRB 352213"
    assert diagnostics["orders"]["BPFI"] == 10.929
    assert manifest["batch_limits"] == {
        "maximum_samples": 2000,
        "maximum_points": 20_000_000,
        "maximum_condition_rows": 100,
    }
