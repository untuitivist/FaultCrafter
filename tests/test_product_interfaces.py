from __future__ import annotations

import json
from http.server import ThreadingHTTPServer
import threading
from urllib.request import ProxyHandler, build_opener

import numpy as np
import pytest

from faultcrafter.cli import main
from faultcrafter.gui.server import WebApplication, handler_for
from faultcrafter.services.application import RuntimeApplication
from faultcrafter.services.locking import ComputeLock
from test_compact_deployment import compact_fixture


def request():
    return {"device_id": "device", "fault_id": "normal", "length": 512, "seed": 42,
            "condition_parameters": {"shaft_speed_rpm": 10.0, "lateral_load_kn": 0.0},
            "condition_units": {"shaft_speed_rpm": "Hz", "lateral_load_kn": "kN"}}


def test_cli_inspection_is_read_only_and_reports_actual_model(tmp_path, capsys):
    root = compact_fixture(tmp_path / "compact")
    state = tmp_path / "state"
    assert main(["inspect", "--model-root", str(root), "--user-data-root", str(state)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["devices"][0]["id"] == "device"
    assert payload["shared_sha256"]
    assert not state.exists()


def test_cli_and_gui_generate_identical_physical_requests(tmp_path):
    root = compact_fixture(tmp_path / "compact")
    state = tmp_path / "state"
    source = tmp_path / "request.json"
    output = tmp_path / "signal.json"
    source.write_text(json.dumps(request()), encoding="utf-8")
    assert main(["generate", "--model-root", str(root), "--user-data-root", str(state),
                 "--compute-device", "cpu", "--request", str(source), "--output", str(output)]) == 0
    actual = json.loads(output.read_text(encoding="utf-8"))
    expected = WebApplication(root, compute_device="cpu", user_data_root=state).generate(request())
    np.testing.assert_array_equal(actual["normalized_signal"], expected["normalized_signal"])
    np.testing.assert_array_equal(actual["physical_signal"], expected["physical_signal"])
    assert actual["condition_conversion"] == expected["condition_conversion"]
    assert actual["shared_sha256"] == expected["shared_sha256"]
    before = output.read_bytes()
    assert main(["generate", "--request", str(source), "--output", str(output)]) == 2
    assert output.read_bytes() == before


def test_cli_reports_missing_models_without_falling_back(tmp_path, capsys):
    assert main(["inspect", "--model-root", str(tmp_path / "missing")]) == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_gui_serves_packaged_assets_and_shared_manifest(tmp_path):
    root = compact_fixture(tmp_path / "compact")
    application = WebApplication(root, user_data_root=tmp_path / "state")
    service = RuntimeApplication(root, user_data_root=tmp_path / "state")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(application))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    client = build_opener(ProxyHandler({}))
    try:
        with client.open(base + "/api/manifest", timeout=5) as response:
            assert json.load(response) == service.public_manifest()
        for path, content in (("/", application.html), ("/onboarding", application.onboarding_html),
                              ("/condition-units.js", application.unit_javascript)):
            with client.open(base + path, timeout=5) as response:
                assert response.read() == content
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_compute_lock_rejects_another_application_and_releases(tmp_path):
    first, second = ComputeLock(tmp_path / "runtime.lock"), ComputeLock(tmp_path / "runtime.lock")
    with first:
        with pytest.raises(RuntimeError, match="占用"):
            with second:
                pytest.fail("Competing application acquired the lock")
    with second:
        pass
