(() => {
  "use strict";

  const units = globalThis.FaultCrafterUnits;

  const elements = {
    device: document.querySelector("#device-select"),
    sensor: document.querySelector("#sensor-select"),
    channelSelect: document.querySelector("#channel-select"),
    fault: document.querySelector("#fault-select"),
    firstField: document.querySelector("#frequency-field"),
    firstLabel: document.querySelector("#frequency-label"),
    firstRange: document.querySelector("#frequency-range"),
    firstNumber: document.querySelector("#frequency-number"),
    firstUnit: document.querySelector("#frequency-unit"),
    firstValues: document.querySelector("#frequency-values"),
    secondField: document.querySelector("#load-field"),
    secondLabel: document.querySelector("#load-label"),
    secondRange: document.querySelector("#load-range"),
    secondNumber: document.querySelector("#load-number"),
    secondUnit: document.querySelector("#load-unit"),
    secondValues: document.querySelector("#load-values"),
    lengthField: document.querySelector("#sample-length-field"),
    lengthLabel: document.querySelector("#sample-length-label"),
    lengthRange: document.querySelector("#sample-length-range"),
    lengthNumber: document.querySelector("#sample-length-number"),
    lengthUnit: document.querySelector("#sample-length-unit"),
    lengthValues: document.querySelector("#sample-length-values"),
    modeButtons: [...document.querySelectorAll("[data-mode]")],
    singlePanel: document.querySelector("#single-generation-panel"),
    batchPanel: document.querySelector("#batch-generation-panel"),
    batchFaultList: document.querySelector("#batch-fault-list"),
    batchSelectAll: document.querySelector("#batch-select-all"),
    batchClearAll: document.querySelector("#batch-clear-all"),
    batchFirstHeading: document.querySelector("#batch-first-heading"),
    batchSecondHeading: document.querySelector("#batch-second-heading"),
    batchConditionBody: document.querySelector("#batch-condition-body"),
    addCondition: document.querySelector("#add-condition-button"),
    batchTotal: document.querySelector("#batch-total"),
    batchBudget: document.querySelector("#batch-budget"),
    batchStart: document.querySelector("#batch-start-button"),
    batchDownload: document.querySelector("#batch-download-button"),
    batchProgress: document.querySelector("#batch-progress"),
    batchProgressText: document.querySelector("#batch-progress-text"),
    batchProgressPercent: document.querySelector("#batch-progress-percent"),
    batchProgressBar: document.querySelector("#batch-progress-bar"),
    generate: document.querySelector("#generate-button"),
    export: document.querySelector("#export-button"),
    exit: document.querySelector("#exit-button"),
    status: document.querySelector("#runtime-status"),
    unitSummary: document.querySelector("#unit-conversion-summary"),
    modelContract: document.querySelector("#model-contract"),
    plot: document.querySelector("#waveform"),
    frame: document.querySelector("#plot-frame"),
    tabs: [...document.querySelectorAll("[data-view]")],
    targetCondition: document.querySelector("#target-condition"),
    channel: document.querySelector("#channel-label"),
    metricWindow: document.querySelector("#metric-window"),
    metricRate: document.querySelector("#metric-rate"),
    metricRms: document.querySelector("#metric-rms"),
    metricPeak: document.querySelector("#metric-peak"),
    diagnosticResolution: document.querySelector("#diagnostic-resolution"),
    diagnosticShaft: document.querySelector("#diagnostic-shaft"),
    diagnosticCharacteristic: document.querySelector("#diagnostic-characteristic"),
    diagnosticMatch: document.querySelector("#diagnostic-match"),
    diagnosticNote: document.querySelector("#diagnostic-note")
  };
  const state = {
    manifest: null, route: null, result: null, requestId: 0, activeView: "waveform",
    mode: "single", batchJobId: null, batchTimer: null, batchLocked: false
  };
  const font = '"Segoe UI", "Microsoft YaHei UI", sans-serif';
  const plotConfig = {
    responsive: true, displaylogo: false, scrollZoom: true,
    doubleClick: "reset+autosize", toImageButtonOptions: { format: "png", scale: 2 }
  };
  const markerColors = { BPFI: "#b7473f", BPFO: "#2468a2", BSF: "#b47b00", FTF: "#76528c" };

  function formatNumber(value) {
    return Number.isInteger(Number(value)) ? String(value) : String(Number(Number(value).toPrecision(8)));
  }

  function humanFault(id) {
    if (id === "normal") return "正常";
    const location = id.startsWith("drive_end_") ? "驱动端轴承 · "
      : id.startsWith("fan_end_") ? "风扇端轴承 · "
      : id.startsWith("left_axlebox_bearing_") ? "左轴箱轴承 · " : "";
    let text = id
      .replace(/^drive_end_/, "")
      .replace(/^fan_end_/, "")
      .replace(/^left_axlebox_bearing_/, "")
      .replace("inner_race", "内圈故障")
      .replace("outer_race", "外圈故障")
      .replace("rolling_element", "滚动体故障")
      .replace("cage", "保持架故障")
      .replace(/_(\d{3})mil/, (_, value) => ` · 0.${value} in`)
      .replace(/_(\d+)deg/, (_, value) => ` · ${Number(value)}°`)
      .replace(/_(300|600|1200)$/, (_, value) => ` · ${value.slice(0, -2)}:${value.slice(-2)}`);
    return location + text;
  }

  function fillSelect(select, rows, selected) {
    select.replaceChildren();
    for (const row of rows) {
      const option = document.createElement("option");
      option.value = row.value;
      option.textContent = row.label;
      select.append(option);
    }
    select.value = selected;
  }

  function configureRange(field, label, range, number, unit, values, control) {
    field.hidden = false;
    label.textContent = control.label;
    range.min = control.minimum;
    range.max = control.maximum;
    range.step = control.step;
    range.value = control.initial;
    number.min = control.minimum;
    number.max = control.maximum;
    number.step = control.step;
    number.value = control.initial;
    if (unit.tagName === "SELECT") {
      fillSelect(unit, control.unit_options.map((option) => ({ value: option.unit, label: option.label })), control.unit);
      unit.dataset.previousUnit = control.unit;
      number.step = "any";
    } else unit.textContent = control.unit;
    const measured = control.measured.map(formatNumber).join(" · ");
    values.textContent = control.range_note || `可调范围 ${formatNumber(control.minimum)}–${formatNumber(control.maximum)} ${control.unit}；实测 ${measured}`;
  }

  function selectedUnit(index) {
    return (index === 0 ? elements.firstUnit : elements.secondUnit).value;
  }

  function conditionUnits() {
    return Object.fromEntries(state.route.parameters.map((control, index) => [control.name, selectedUnit(index)]));
  }

  function refreshUnitSummary() {
    if (!state.route) return;
    if (state.mode === "batch") {
      elements.unitSummary.textContent = "批量工况按每行所选单位独立换算；后端校验标准物理值，并在任务记录中保留换算明细。";
      return;
    }
    try {
      const parameters = conditionParameters();
      elements.unitSummary.textContent = "标准工况：" + state.route.parameters.map((control, index) =>
        `${control.label} ${formatNumber(units.canonical(control, parameters[control.name], selectedUnit(index)))} ${control.canonical_unit}`
      ).join(" / ") + "。后端统一校验，再等价换算到原模型输入单位。";
    } catch (error) {
      elements.unitSummary.textContent = error.message;
    }
  }

  function setInputUnit(control, input, sourceUnit, targetUnit, range = null) {
    const converted = input.value === "" ? "" : units.convert(control, input.value, sourceUnit, targetUnit);
    input.min = units.convert(control, control.minimum, control.unit, targetUnit);
    input.max = units.convert(control, control.maximum, control.unit, targetUnit);
    input.step = "any";
    input.value = converted;
    if (range) {
      range.min = input.min;
      range.max = input.max;
      range.step = units.convert(control, control.step, control.unit, targetUnit);
      if (converted !== "") range.value = converted;
    }
  }

  function changeSingleUnit(index) {
    const control = state.route.parameters[index];
    const select = index === 0 ? elements.firstUnit : elements.secondUnit;
    const number = index === 0 ? elements.firstNumber : elements.secondNumber;
    const range = index === 0 ? elements.firstRange : elements.secondRange;
    try {
      setInputUnit(control, number, select.dataset.previousUnit, select.value, range);
    } catch (error) {
      select.value = select.dataset.previousUnit;
      elements.status.textContent = error.message;
      refreshUnitSummary();
      return;
    }
    select.dataset.previousUnit = select.value;
    const values = index === 0 ? elements.firstValues : elements.secondValues;
    const measured = control.measured.map((value) => formatNumber(units.convert(control, value, control.unit, select.value))).join(" · ");
    values.textContent = control.range_note || `可调范围 ${formatNumber(number.min)}–${formatNumber(number.max)} ${select.value}；实测 ${measured}`;
    if (state.result) elements.targetCondition.textContent = targetText(state.result.condition_parameters);
    refreshUnitSummary();
    elements.status.textContent = "单位已切换，物理工况保持不变；未重新生成信号。";
  }

  function renderFaults(route) {
    elements.fault.replaceChildren();
    const groups = new Map();
    for (const fault of route.faults) {
      const groupName = fault.group || "故障";
      if (!groups.has(groupName)) {
        const group = document.createElement("optgroup");
        group.label = groupName;
        groups.set(groupName, group);
        elements.fault.append(group);
      }
      const option = document.createElement("option");
      option.value = fault.id;
      option.textContent = humanFault(fault.id);
      groups.get(groupName).append(option);
    }
  }

  function renderBatchFaults(route) {
    elements.batchFaultList.replaceChildren();
    for (const [index, fault] of route.faults.entries()) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = fault.id;
      input.checked = index === 0;
      input.addEventListener("change", updateBatchSummary);
      const text = document.createElement("span");
      text.textContent = humanFault(fault.id);
      text.title = text.textContent;
      label.append(input, text);
      elements.batchFaultList.append(label);
    }
  }

  function selectRoute(deviceId) {
    const route = state.manifest.devices.find((item) => item.id === deviceId);
    if (!route) throw new Error(`未知设备: ${deviceId}`);
    state.route = route;
    const fixedNote = document.getElementById("fixed-conditions-note");
    const fixedLabels = {shaft_torque_nm: "轴扭矩（Nm）", radial_force_n: "径向力（N）", lateral_load_n: "横向力（N）", shaft_speed_rpm: "轴转速（rpm）", motor_load_w: "标注功率（W）"};
    const fixed = Object.entries(route.fixed_conditions || {});
    fixedNote.hidden = fixed.length === 0;
    fixedNote.textContent = `本设备固定工况：${fixed.map(([name, value]) => `${fixedLabels[name] || name} ${value}`).join("；")}。本次生成沿用这些工况。`;
    fillSelect(elements.sensor, [{ value: route.sensor_label, label: route.sensor_label }], route.sensor_label);
    fillSelect(elements.channelSelect, [{ value: route.channel, label: route.channel }], route.channel);
    configureRange(
      elements.firstField, elements.firstLabel, elements.firstRange,
      elements.firstNumber, elements.firstUnit, elements.firstValues, route.parameters[0]
    );
    if (route.parameters.length > 1) {
      configureRange(
        elements.secondField, elements.secondLabel, elements.secondRange,
        elements.secondNumber, elements.secondUnit, elements.secondValues, route.parameters[1]
      );
    } else {
      elements.secondField.hidden = true;
    }
    renderFaults(route);
    renderBatchFaults(route);
    resetBatchConditions();
    resetAnalysis();
    refreshUnitSummary();
    elements.status.textContent = state.mode === "single"
      ? "参数已就绪，点击“生成信号”运行本地 JiT 推理。"
      : "批量配置已就绪，请选择故障并填写工况行。";
  }

  function resetAnalysis() {
    state.result = null;
    state.activeView = "waveform";
    elements.export.disabled = true;
    elements.targetCondition.textContent = "目标工况";
    elements.channel.textContent = "Acceleration";
    for (const metric of [elements.metricWindow, elements.metricRate, elements.metricRms, elements.metricPeak]) {
      metric.textContent = "-";
    }
    for (const metric of [
      elements.diagnosticResolution, elements.diagnosticShaft,
      elements.diagnosticCharacteristic, elements.diagnosticMatch
    ]) metric.textContent = "-";
    elements.diagnosticNote.textContent = "生成后显示频域诊断；该指标用于筛查，不等同于真实性证明。";
    setActiveTab("waveform");
    Plotly.purge(elements.plot);
  }

  function bindPair(range, number, preserveTypedValue = false) {
    range.addEventListener("input", () => {
      number.value = range.value;
      refreshUnitSummary();
      elements.status.textContent = "参数已修改，点击“生成信号”更新波形。";
    });
    number.addEventListener("input", () => {
      const value = Number(number.value);
      if (!Number.isFinite(value)) return;
      range.value = String(Math.min(Number(range.max), Math.max(Number(range.min), value)));
      refreshUnitSummary();
      elements.status.textContent = "参数已修改，点击“生成信号”更新波形。";
    });
    number.addEventListener("change", () => {
      if (!preserveTypedValue) number.value = range.value;
      refreshUnitSummary();
    });
  }

  function conditionParameters() {
    const result = { [state.route.parameters[0].name]: units.numeric(elements.firstNumber.value) };
    if (state.route.parameters.length > 1) {
      result[state.route.parameters[1].name] = units.numeric(elements.secondNumber.value);
    }
    return result;
  }

  function selectedBatchFaults() {
    return [...elements.batchFaultList.querySelectorAll('input[type="checkbox"]:checked')]
      .map((input) => input.value);
  }

  function batchLabel(row) {
    const parts = [...row.querySelectorAll("[data-parameter]")].map((input) => {
      const control = state.route.parameters[Number(input.dataset.parameter)];
      const unit = row.querySelector(`[data-unit="${input.dataset.parameter}"]`).value;
      return `${formatNumber(input.value)}${unit}`;
    });
    const length = row.querySelector("[data-length]").value;
    const count = row.querySelector("[data-count]").value;
    return [...parts, `${length}pt`, `n${count}`].join("_");
  }

  function refreshBatchRows() {
    const rows = [...elements.batchConditionBody.rows];
    for (const row of rows) {
      row.querySelector("[data-label]").textContent = batchLabel(row);
      row.querySelector("[data-remove]").disabled = state.batchLocked || rows.length === 1;
    }
    updateBatchSummary();
  }

  function numberInput(attributes) {
    const input = document.createElement("input");
    input.type = "number";
    for (const [name, value] of Object.entries(attributes)) input[name] = value;
    input.addEventListener("input", refreshBatchRows);
    return input;
  }

  function addBatchCondition(values = null) {
    const runtime = state.manifest.runtime;
    const row = elements.batchConditionBody.insertRow();
    const labelCell = row.insertCell();
    const label = document.createElement("span");
    label.className = "batch-label";
    label.dataset.label = "";
    labelCell.append(label);
    for (const [index, control] of state.route.parameters.entries()) {
      const cell = row.insertCell();
      const input = numberInput({
        min: control.minimum, max: control.maximum, step: control.step,
        value: values?.parameters?.[control.name] ?? control.initial
      });
      input.dataset.parameter = String(index);
      const select = document.createElement("select");
      select.className = "condition-unit-select";
      select.dataset.unit = String(index);
      select.setAttribute("aria-label", `${control.label}单位`);
      fillSelect(select, control.unit_options.map((option) => ({ value: option.unit, label: option.label })), control.unit);
      select.dataset.previousUnit = control.unit;
      input.step = "any";
      select.addEventListener("change", () => {
        try {
          setInputUnit(control, input, select.dataset.previousUnit, select.value);
          select.dataset.previousUnit = select.value;
        } catch (error) {
          select.value = select.dataset.previousUnit;
          elements.status.textContent = error.message;
        }
        refreshBatchRows();
      });
      const group = document.createElement("div");
      group.className = "unit-input-group";
      group.append(input, select);
      cell.append(group);
    }
    if (state.route.parameters.length === 1) {
      const emptyCell = row.insertCell();
      emptyCell.hidden = true;
    }
    const lengthCell = row.insertCell();
    const length = numberInput({
      min: runtime.minimum_length, max: runtime.maximum_length, step: 1,
      value: values?.length ?? runtime.default_length
    });
    length.dataset.length = "";
    lengthCell.append(length);
    const countCell = row.insertCell();
    const count = numberInput({ min: 1, max: 1000, step: 1, value: values?.count ?? 10 });
    count.dataset.count = "";
    countCell.append(count);
    const actionCell = row.insertCell();
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-condition-button";
    remove.dataset.remove = "";
    remove.title = "删除工况";
    remove.setAttribute("aria-label", "删除工况");
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      row.remove();
      refreshBatchRows();
    });
    actionCell.append(remove);
    refreshBatchRows();
  }

  function resetBatchConditions() {
    elements.batchConditionBody.replaceChildren();
    elements.batchFirstHeading.textContent = `${state.route.parameters[0].label}（数值 / 单位）`;
    elements.batchSecondHeading.hidden = state.route.parameters.length === 1;
    if (state.route.parameters.length > 1) {
      elements.batchSecondHeading.textContent = `${state.route.parameters[1].label}（数值 / 单位）`;
    }
    addBatchCondition();
    resetBatchProgress();
  }

  function batchConditions() {
    return [...elements.batchConditionBody.rows].map((row) => {
      const parameters = {};
      const conditionUnitValues = {};
      for (const input of row.querySelectorAll("[data-parameter]")) {
        const control = state.route.parameters[Number(input.dataset.parameter)];
        parameters[control.name] = input.value === "" ? NaN : Number(input.value);
        conditionUnitValues[control.name] = row.querySelector(`[data-unit="${input.dataset.parameter}"]`).value;
      }
      return {
        condition_parameters: parameters,
        condition_units: conditionUnitValues,
        length: Number(row.querySelector("[data-length]").value),
        count: Number(row.querySelector("[data-count]").value)
      };
    });
  }

  function updateBatchSummary() {
    if (!state.manifest || !state.route) return;
    const faults = selectedBatchFaults().length;
    const rows = batchConditions();
    const samples = faults * rows.reduce((sum, row) => sum + (Number.isFinite(row.count) ? row.count : 0), 0);
    const points = faults * rows.reduce((sum, row) => sum + (
      Number.isFinite(row.count) && Number.isFinite(row.length) ? row.count * row.length : 0
    ), 0);
    const limits = state.manifest.batch_limits;
    elements.batchTotal.textContent = `${samples.toLocaleString("zh-CN")} / ${limits.maximum_samples.toLocaleString("zh-CN")} 条样本`;
    elements.batchBudget.textContent = `${points.toLocaleString("zh-CN")} / ${limits.maximum_points.toLocaleString("zh-CN")} 点`;
    const validRows = rows.length > 0 && rows.every((row) => {
      const parametersValid = state.route.parameters.every((control) => units.withinLimits(
        control, row.condition_parameters[control.name], row.condition_units[control.name]
      ));
      return parametersValid
        && Number.isInteger(row.length)
        && row.length >= state.manifest.runtime.minimum_length
        && row.length <= state.manifest.runtime.maximum_length
        && Number.isInteger(row.count) && row.count >= 1 && row.count <= 1000;
    });
    elements.batchStart.disabled = state.batchLocked || faults === 0 || !validRows
      || samples > limits.maximum_samples || points > limits.maximum_points;
  }

  function resetBatchProgress() {
    state.batchJobId = null;
    if (state.batchTimer) clearTimeout(state.batchTimer);
    state.batchTimer = null;
    elements.batchProgress.hidden = true;
    elements.batchProgressBar.value = 0;
    elements.batchProgressPercent.textContent = "0%";
    elements.batchProgressText.textContent = "等待开始";
    elements.batchDownload.hidden = true;
    elements.batchDownload.removeAttribute("href");
  }

  function setBatchLocked(locked) {
    state.batchLocked = locked;
    elements.device.disabled = locked;
    elements.sensor.disabled = locked;
    elements.channelSelect.disabled = locked;
    elements.addCondition.disabled = locked;
    for (const button of elements.modeButtons) button.disabled = locked;
    for (const control of elements.batchPanel.querySelectorAll("input, select, button")) control.disabled = locked;
    updateBatchSummary();
  }

  function setMode(mode) {
    if (state.batchLocked || mode === state.mode) return;
    state.mode = mode;
    const batch = mode === "batch";
    document.querySelector(".app-shell").classList.toggle("batch-mode", batch);
    elements.singlePanel.hidden = batch;
    elements.batchPanel.hidden = !batch;
    elements.generate.hidden = batch;
    elements.export.hidden = batch;
    elements.batchStart.hidden = !batch;
    for (const button of elements.modeButtons) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
    }
    elements.status.textContent = batch
      ? "选择一个或多个故障，添加工况行后开始批量生成。"
      : "参数已就绪，点击“生成信号”运行本地 JiT 推理。";
    refreshUnitSummary();
    updateBatchSummary();
  }

  function signalStats(values) {
    let sum = 0, minimum = Infinity, maximum = -Infinity;
    for (const value of values) {
      sum += value * value;
      minimum = Math.min(minimum, value);
      maximum = Math.max(maximum, value);
    }
    return { rms: Math.sqrt(sum / values.length), peakToPeak: maximum - minimum };
  }

  function targetText(parameters) {
    return "目标工况 " + state.route.parameters.map((control, index) =>
      `${formatNumber(units.convert(control, parameters[control.name], control.unit, selectedUnit(index)))} ${selectedUnit(index)}`
    ).join(" / ");
  }

  function baseLayout(xTitle, yTitle) {
    return {
      autosize: true, margin: { top: 52, right: 24, bottom: 54, left: 68 },
      paper_bgcolor: "#fff", plot_bgcolor: "#fff", showlegend: false,
      font: { family: font, color: "#182327" },
      xaxis: { title: xTitle, gridcolor: "#e5ebec", zeroline: false },
      yaxis: { title: yTitle, gridcolor: "#e5ebec", zerolinecolor: "#bcc9cb" }
    };
  }

  function markerDecorations(markers, coordinate) {
    const shapes = [];
    const annotations = [];
    for (const marker of markers) {
      const x = coordinate === "order" ? marker.order : marker.frequency_hz;
      const color = markerColors[marker.code] || "#6c7779";
      shapes.push({
        type: "line", x0: x, x1: x, y0: 0, y1: 1, xref: "x", yref: "paper",
        line: { color, width: marker.selected ? 1.8 : 1, dash: marker.selected ? "solid" : "dot" },
        opacity: marker.selected ? 0.88 : 0.55
      });
      if (marker.harmonic === 1 || marker.selected) {
        annotations.push({
          x, y: marker.selected ? 1.02 : 0.92, xref: "x", yref: "paper",
          text: marker.harmonic === 1 ? marker.code : `${marker.code} ${marker.harmonic}×`,
          showarrow: false, textangle: -90, xanchor: "left",
          font: { family: font, size: 9, color }
        });
      }
    }
    return { shapes, annotations };
  }

  function drawWaveform(result) {
    const values = result.physical_signal;
    const milliseconds = values.map((_, index) => index / result.sample_rate_hz * 1000);
    let peak = Math.max(...values.map(Math.abs)) * 1.12;
    peak = Math.max(peak, 1e-6);
    const layout = baseLayout("时间 (ms)", `幅值 (${result.physical_unit})`);
    layout.xaxis.range = [0, milliseconds.at(-1)];
    layout.yaxis.range = [-peak, peak];
    Plotly.react(elements.plot, [{
      x: milliseconds, y: values, type: "scatter", mode: "lines",
      line: { color: "#087d74", width: 1.25, simplify: false },
      hovertemplate: "时间 %{x:.3f} ms<br>幅值 %{y:.5g}<extra></extra>"
    }], layout, plotConfig);
  }

  function drawSpectrum(result, envelope = false) {
    const source = envelope ? result.analysis.envelope_spectrum : result.analysis.frequency_spectrum;
    const layout = baseLayout("频率 (Hz)", envelope ? "包络幅值" : `幅值 (${result.physical_unit})`);
    const decorations = markerDecorations(result.analysis.diagnostics.markers, "frequency");
    layout.shapes = decorations.shapes;
    layout.annotations = decorations.annotations;
    layout.xaxis.range = [0, result.analysis.diagnostics.maximum_frequency_hz];
    Plotly.react(elements.plot, [{
      x: source.frequency_hz, y: source.amplitude, type: "scatter", mode: "lines",
      line: { color: envelope ? "#b56f20" : "#087d74", width: 1.3 },
      fill: "tozeroy", fillcolor: envelope ? "rgba(181,111,32,.10)" : "rgba(8,125,116,.10)",
      hovertemplate: "%{x:.2f} Hz<br>幅值 %{y:.5g}<extra></extra>"
    }], layout, plotConfig);
  }

  function shaftFrequency(result) {
    const bearing = result.analysis.diagnostics.bearing;
    if (bearing) return bearing.shaft_frequency_hz;
    const control = state.route.parameters[state.route.speed_parameter_index];
    return result.condition_parameters[control.name] * state.route.speed_to_hz;
  }

  function drawOrderSpectrum(result) {
    const shaftHz = shaftFrequency(result);
    const source = result.analysis.envelope_spectrum;
    const orders = source.frequency_hz.map((frequency) => frequency / shaftHz);
    const layout = baseLayout("阶次 (×轴频)", "包络幅值");
    const decorations = markerDecorations(result.analysis.diagnostics.markers, "order");
    layout.shapes = decorations.shapes;
    layout.annotations = decorations.annotations;
    layout.xaxis.range = [0, Math.min(40, orders.at(-1))];
    Plotly.react(elements.plot, [{
      x: orders, y: source.amplitude, type: "scatter", mode: "lines",
      line: { color: "#5b568f", width: 1.3 },
      fill: "tozeroy", fillcolor: "rgba(91,86,143,.10)",
      hovertemplate: "%{x:.3f}×<br>幅值 %{y:.5g}<extra></extra>"
    }], layout, plotConfig);
  }

  function drawSpectrogram(result) {
    const source = result.analysis.spectrogram;
    const layout = baseLayout("时间 (s)", "频率 (Hz)");
    layout.margin.right = 74;
    const x = [], y = [], color = [];
    for (let frequencyIndex = 0; frequencyIndex < source.frequency_hz.length; frequencyIndex += 1) {
      for (let timeIndex = 0; timeIndex < source.time_seconds.length; timeIndex += 1) {
        x.push(source.time_seconds[timeIndex]);
        y.push(source.frequency_hz[frequencyIndex]);
        color.push(source.amplitude_db[frequencyIndex][timeIndex]);
      }
    }
    Plotly.react(elements.plot, [{
      x, y, type: "scatter", mode: "markers",
      marker: {
        symbol: "square", size: Math.max(4, Math.min(14, 420 / source.frequency_hz.length)),
        color, cmin: -60, cmax: 0, showscale: true,
        colorscale: [[0, "#f1f4f3"], [0.35, "#a8ccc7"], [0.7, "#218e83"], [1, "#173a3c"]],
        colorbar: { title: "dB", thickness: 12, len: 0.72 }
      },
      hovertemplate: "%{x:.4f} s<br>%{y:.1f} Hz<br>%{marker.color:.1f} dB<extra></extra>"
    }], layout, plotConfig);
  }

  function setActiveTab(view) {
    state.activeView = view;
    for (const tab of elements.tabs) {
      const selected = tab.dataset.view === view;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    }
  }

  function drawActiveView() {
    if (!state.result) return;
    if (state.activeView === "waveform") drawWaveform(state.result);
    else if (state.activeView === "spectrum") drawSpectrum(state.result);
    else if (state.activeView === "envelope") drawSpectrum(state.result, true);
    else if (state.activeView === "order") drawOrderSpectrum(state.result);
    else drawSpectrogram(state.result);
  }

  function updateDiagnostics(result) {
    const diagnostics = result.analysis.diagnostics;
    const resolution = diagnostics.frequency_resolution_hz;
    elements.diagnosticResolution.textContent = `${resolution.toFixed(resolution < 10 ? 2 : 1)} Hz`;
    const shaftHz = shaftFrequency(result);
    const bearing = diagnostics.bearing;
    elements.diagnosticShaft.textContent = `${shaftHz.toFixed(2)} Hz${bearing ? "（估算）" : ""}`;
    if (!bearing) {
      elements.diagnosticCharacteristic.textContent = "未录入轴承结构参数";
      elements.diagnosticMatch.textContent = "仅显示通用频谱";
      elements.diagnosticNote.textContent = result.physical_signal.length < diagnostics.recommended_minimum_length
        ? "当前长度的频率分辨率有限；真实性判断建议使用 8192 点以上并与真实数据统计对照。"
        : "当前设备未录入轴承几何阶次；频谱用于观察，不能单独判定真实性。";
      return;
    }
    if (bearing.selected_code) {
      elements.diagnosticCharacteristic.textContent = `${bearing.selected_code} ${bearing.selected_frequency_hz.toFixed(2)} Hz`;
      const match = bearing.match;
      elements.diagnosticMatch.textContent = match
        ? `${match.peak_frequency_hz.toFixed(2)} Hz / ${match.prominence_db.toFixed(1)} dB`
        : "分析带宽内未匹配";
    } else {
      elements.diagnosticCharacteristic.textContent = "正常状态（无故障标线）";
      elements.diagnosticMatch.textContent = "-";
    }
    const prefix = result.physical_signal.length < diagnostics.recommended_minimum_length
      ? "当前长度低于 8192 点，频率分辨率有限。"
      : "理论标线只用于结构一致性筛查。";
    elements.diagnosticNote.textContent = `${prefix}${bearing.assumption}`;
  }

  async function generate() {
    const requestId = ++state.requestId;
    elements.generate.disabled = true;
    elements.export.disabled = true;
    elements.status.textContent = "正在运行本地统一 JiT 模型…";
    try {
      const response = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: state.route.id,
          fault_id: elements.fault.value,
          condition_parameters: conditionParameters(),
          condition_units: conditionUnits(),
          length: Number(elements.lengthRange.value),
          seed: Math.floor(Math.random() * 2147483647)
        })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      if (requestId !== state.requestId) return;
      state.result = payload;
      const stats = signalStats(payload.physical_signal);
      elements.targetCondition.textContent = targetText(payload.condition_parameters);
      elements.channel.textContent = `${state.route.sensor_label} · ${state.route.channel} · ${state.route.quantity_label}`;
      elements.metricWindow.textContent = `${payload.physical_signal.length.toLocaleString("zh-CN")} 点`;
      elements.metricRate.textContent = `${payload.sample_rate_hz.toLocaleString("zh-CN")} Hz`;
      elements.metricRms.textContent = stats.rms.toPrecision(4);
      elements.metricPeak.textContent = stats.peakToPeak.toPrecision(4);
      updateDiagnostics(payload);
      drawActiveView();
      elements.export.disabled = false;
      elements.status.textContent = `生成完成 · ${payload.compute_device} · ${payload.elapsed_seconds.toFixed(2)} s · 幅值尺度 ${payload.predicted_amplitude.toPrecision(4)}`;
    } catch (error) {
      elements.status.textContent = `生成失败：${error.message}`;
    } finally {
      elements.generate.disabled = false;
    }
  }

  function exportCsv() {
    if (!state.result) return;
    const rows = ["sample_index,time_seconds,normalized_signal,physical_signal"];
    for (let index = 0; index < state.result.physical_signal.length; index += 1) {
      rows.push([
        index,
        (index / state.result.sample_rate_hz).toPrecision(12),
        state.result.normalized_signal[index].toPrecision(9),
        state.result.physical_signal[index].toPrecision(9)
      ].join(","));
    }
    const blob = new Blob(["\ufeff" + rows.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `faultcrafter-${state.route.id}-${state.result.fault_id}-${state.result.seed}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function startBatch() {
    resetBatchProgress();
    setBatchLocked(true);
    elements.batchProgress.hidden = false;
    elements.batchProgressText.textContent = "正在创建批量任务…";
    elements.status.textContent = "正在提交批量生成任务…";
    try {
      const response = await fetch("/api/batch/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: state.route.id,
          fault_ids: selectedBatchFaults(),
          conditions: batchConditions()
        })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      state.batchJobId = payload.job_id;
      updateBatchProgress(payload);
      await pollBatch();
    } catch (error) {
      elements.batchProgressText.textContent = `任务失败：${error.message}`;
      elements.status.textContent = `批量生成失败：${error.message}`;
      setBatchLocked(false);
    }
  }

  function updateBatchProgress(payload) {
    const progress = Math.max(0, Math.min(1, Number(payload.progress) || 0));
    elements.batchProgressBar.value = progress;
    elements.batchProgressPercent.textContent = `${Math.round(progress * 100)}%`;
    if (payload.status === "completed") {
      elements.batchProgressText.textContent = `已完成 ${payload.total_samples.toLocaleString("zh-CN")} 条样本`;
    } else if (payload.status === "failed") {
      elements.batchProgressText.textContent = `任务失败：${payload.error || "未知错误"}`;
    } else {
      const current = payload.current_label
        ? ` · ${payload.current_label} · ${humanFault(payload.current_fault_id)}` : "";
      elements.batchProgressText.textContent = `${payload.completed_samples.toLocaleString("zh-CN")} / ${payload.total_samples.toLocaleString("zh-CN")}${current}`;
    }
  }

  async function pollBatch() {
    if (!state.batchJobId) return;
    try {
      const response = await fetch(`/api/batch/status?job_id=${encodeURIComponent(state.batchJobId)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      updateBatchProgress(payload);
      if (payload.status === "completed") {
        elements.batchDownload.href = `/api/batch/download?job_id=${encodeURIComponent(state.batchJobId)}`;
        elements.batchDownload.download = payload.archive_name || "faultcrafter-batch.zip";
        elements.batchDownload.hidden = false;
        elements.status.textContent = `批量生成完成 · ${payload.total_samples.toLocaleString("zh-CN")} 条样本 · 点击下载 ZIP`;
        setBatchLocked(false);
        return;
      }
      if (payload.status === "failed") {
        elements.status.textContent = `批量生成失败：${payload.error || "未知错误"}`;
        setBatchLocked(false);
        return;
      }
      state.batchTimer = setTimeout(() => { pollBatch(); }, 750);
    } catch (error) {
      elements.batchProgressText.textContent = `状态读取失败：${error.message}`;
      elements.status.textContent = `批量任务状态读取失败：${error.message}`;
      setBatchLocked(false);
    }
  }

  async function exitApplication() {
    elements.exit.disabled = true;
    elements.status.textContent = "正在退出本地应用…";
    try {
      const response = await fetch("/api/shutdown", { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      document.querySelector(".app-shell").classList.add("app-exited");
      elements.exit.textContent = "已退出";
      elements.status.textContent = "本地应用已退出，可以关闭此页面。";
    } catch (error) {
      elements.exit.disabled = false;
      elements.status.textContent = `无法退出：${error.message}`;
    }
  }

  async function initialize() {
    const response = await fetch("/api/manifest");
    if (!response.ok) throw new Error(`无法读取模型清单: HTTP ${response.status}`);
    state.manifest = await response.json();
    elements.modelContract.textContent = `${state.manifest.model_label} · ${state.manifest.model_id}。${state.manifest.model_scope || ""}`;
    fillSelect(
      elements.device,
      state.manifest.devices.map((route) => ({ value: route.id, label: route.label })),
      state.manifest.devices[0].id
    );
    const runtime = state.manifest.runtime;
    configureRange(
      elements.lengthField, elements.lengthLabel, elements.lengthRange,
      elements.lengthNumber, elements.lengthUnit, elements.lengthValues,
      {
        label: "样本长度", unit: "点", minimum: runtime.minimum_length,
        maximum: runtime.maximum_length, step: 1, initial: runtime.default_length,
        measured: state.manifest.training_lengths
      }
    );
    bindPair(elements.firstRange, elements.firstNumber, true);
    bindPair(elements.secondRange, elements.secondNumber, true);
    elements.firstUnit.addEventListener("change", () => changeSingleUnit(0));
    elements.secondUnit.addEventListener("change", () => changeSingleUnit(1));
    bindPair(elements.lengthRange, elements.lengthNumber);
    elements.device.addEventListener("change", () => selectRoute(elements.device.value));
    elements.generate.addEventListener("click", generate);
    elements.export.addEventListener("click", exportCsv);
    elements.batchStart.addEventListener("click", startBatch);
    elements.addCondition.addEventListener("click", () => {
      if (elements.batchConditionBody.rows.length >= state.manifest.batch_limits.maximum_condition_rows) {
        elements.status.textContent = `最多可添加 ${state.manifest.batch_limits.maximum_condition_rows} 行工况。`;
        return;
      }
      addBatchCondition();
    });
    elements.batchSelectAll.addEventListener("click", () => {
      for (const input of elements.batchFaultList.querySelectorAll('input[type="checkbox"]')) input.checked = true;
      updateBatchSummary();
    });
    elements.batchClearAll.addEventListener("click", () => {
      for (const input of elements.batchFaultList.querySelectorAll('input[type="checkbox"]')) input.checked = false;
      updateBatchSummary();
    });
    elements.exit.addEventListener("click", exitApplication);
    for (const button of elements.modeButtons) {
      button.addEventListener("click", () => setMode(button.dataset.mode));
    }
    elements.fault.addEventListener("change", () => {
      elements.status.textContent = "故障类型已修改，点击“生成信号”更新波形。";
    });
    for (const tab of elements.tabs) {
      tab.addEventListener("click", () => {
        setActiveTab(tab.dataset.view);
        drawActiveView();
      });
    }
    const requestedDevice = new URLSearchParams(location.search).get("device");
    const initialDevice = state.manifest.devices.some((route) => route.id === requestedDevice) ? requestedDevice : state.manifest.devices[0].id;
    elements.device.value = initialDevice;
    selectRoute(initialDevice);
    new ResizeObserver(() => { if (elements.plot.data) Plotly.Plots.resize(elements.plot); }).observe(elements.frame);
  }

  initialize().catch((error) => { elements.status.textContent = `初始化失败：${error.message}`; });
})();
