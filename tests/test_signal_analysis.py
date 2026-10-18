from __future__ import annotations

import numpy as np
import pytest

from faultcrafter.signal_analysis import analyze_signal


BJTU_DIAGNOSTICS = {
    "bearing_model": "HRB 352213",
    "shaft_frequency_label": "axle",
    "source_parameter": "drive_frequency_hz",
    "shaft_frequency_ratio": 16 / 107,
    "orders": {"BPFI": 10.929, "BPFO": 8.071, "BSF": 3.164, "FTF": 0.425},
    "fault_order_map": {
        "inner_race": "BPFI",
        "outer_race": "BPFO",
        "rolling_element": "BSF",
        "cage": "FTF",
    },
    "assumption": "test",
}


def test_frequency_and_envelope_spectra_recover_known_components() -> None:
    sample_rate = 4_096
    time = np.arange(sample_rate, dtype=np.float64) / sample_rate
    signal = (1.0 + 0.5 * np.cos(2 * np.pi * 30 * time)) * np.cos(
        2 * np.pi * 500 * time
    )
    analysis = analyze_signal(
        signal,
        sample_rate,
        fault_id="normal",
        condition_parameters={"shaft_speed_rpm": 600.0},
    )
    spectrum = analysis["frequency_spectrum"]
    frequency_peak = spectrum["frequency_hz"][int(np.argmax(spectrum["amplitude"]))]
    envelope = analysis["envelope_spectrum"]
    nonzero = np.asarray(envelope["frequency_hz"]) > 0
    envelope_peak = np.asarray(envelope["frequency_hz"])[nonzero][
        int(np.argmax(np.asarray(envelope["amplitude"])[nonzero]))
    ]
    assert frequency_peak == pytest.approx(500.0)
    assert envelope_peak == pytest.approx(30.0)
    assert analysis["spectrogram"]["amplitude_db"]


def test_bjtu_diagnostics_use_fixed_order_and_speed_scaled_frequency() -> None:
    sample_rate = 64_000
    signal = np.sin(2 * np.pi * 65.4 * np.arange(16_384) / sample_rate)
    analysis = analyze_signal(
        signal,
        sample_rate,
        fault_id="left_axlebox_bearing_inner_race",
        condition_parameters={"drive_frequency_hz": 40.0, "lateral_load_kn": 0.0},
        bearing_diagnostics=BJTU_DIAGNOSTICS,
    )
    bearing = analysis["diagnostics"]["bearing"]
    assert bearing["shaft_frequency_hz"] == pytest.approx(40 * 16 / 107)
    assert bearing["selected_code"] == "BPFI"
    assert bearing["selected_frequency_hz"] == pytest.approx(
        10.929 * 40 * 16 / 107
    )
    selected = [
        marker
        for marker in analysis["diagnostics"]["markers"]
        if marker["selected"] and marker["harmonic"] == 1
    ]
    assert selected[0]["order"] == pytest.approx(10.929)
