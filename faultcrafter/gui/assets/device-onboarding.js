(() => {
  "use strict";
  const element = (name) => document.getElementById(name);
  let activeJob = null;
  let watching = null;
  async function api(path, payload) {
    const response = await fetch(path, payload === undefined ? {} : {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `请求失败：${response.status}`);
    return result;
  }
  function display(status) {
    activeJob = status.job_id;
    const labels = {uploading:"等待文件上传", validated:"数据校验通过，可以训练", training:"训练中，可以关闭页面，保持本地服务运行", ready:"设备已注册，可以生成", failed:"任务失败，日志已保留", interrupted:"训练被中断，日志已保留"};
    element("status").textContent = `${status.device_id}\n${labels[status.state] || status.state}\n训练进度：${status.step || 0} / ${status.maximum_steps}\n${status.validation ? `训练记录 ${status.validation.train_records}，验证记录 ${status.validation.validation_records}` : ""}${status.error ? `\n${status.error}` : ""}`;
    element("progress").max = status.maximum_steps;
    element("progress").value = status.step || 0;
    element("train").disabled = status.state !== "validated";
    element("generate").hidden = status.state !== "ready";
    element("download").hidden = status.state !== "ready";
    element("generate").href = `/?device=${encodeURIComponent(status.device_id)}`;
    element("download").href = status.download_url || "#";
  }
  async function watch(jobId) {
    watching = jobId;
    while (watching === jobId) {
      const status = await api(`/api/devices/status?job_id=${encodeURIComponent(jobId)}&wait=60`);
      if (watching !== jobId) return;
      display(status);
      if (status.state !== "training") break;
    }
  }
  async function manifest() {
    const imported = element("manifest").files[0];
    if (imported) return JSON.parse(await imported.text());
    const names = [element("speed").value, element("load").value].filter(Boolean);
    const lines = element("records").value.trim().split(/\r?\n/);
    if (lines.shift().replace(/\s/g, "") !== "file,fault,split,speed,load") throw new Error("记录清单首行须为 file,fault,split,speed,load");
    const records = lines.filter((line) => line.trim()).map((line, index) => {
      const fields = line.split(",").map((value) => value.trim());
      if (fields.length !== 5 || fields[3] === "" || (names.length === 2 && fields[4] === "")) throw new Error(`第${index + 2}行格式不正确`);
      const conditions = {[names[0]]: Number(fields[3])};
      if (names.length === 2) conditions[names[1]] = Number(fields[4]);
      return {record_id: `record_${index + 1}`, file: fields[0], fault: fields[1], split: fields[2], conditions};
    });
    return {schema:"faultcrafter_device_upload_v1", device_id:element("device").value.trim(),
      dataset_id:element("dataset").value.trim(), sensor_location:element("sensor").value.trim(),
      channel:element("channel").value.trim(), physical_unit:element("unit").value,
      sample_rate_hz:Number(element("rate").value), sampling_policy:"declared_rate_sample_index",
      parameter_names:names, fixed_conditions:element("torque").value === "" ? {} : {shaft_torque_nm:Number(element("torque").value)}, records};
  }
  element("upload").onclick = async () => {
    element("upload").disabled = true;
    try {
      const payload = await manifest();
      const files = new Map(Array.from(element("files").files, (file) => [file.name, file]));
      for (const row of payload.records) if (!files.has(row.file)) throw new Error(`尚未选择文件：${row.file}`);
      const created = await api("/api/devices/create", payload);
      display(created);
      let completed = 0;
      for (const row of payload.records) {
        const response = await fetch(`/api/devices/upload?job_id=${created.job_id}&file=${encodeURIComponent(row.file)}`, {method:"POST", body:files.get(row.file)});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error);
        element("upload-status").textContent = `已上传 ${++completed} / ${payload.records.length}`;
      }
      element("upload-status").textContent = "正在校验信号和记录隔离…";
      display(await api("/api/devices/validate", {job_id:created.job_id}));
      element("upload-status").textContent = "校验通过";
    } catch (error) { element("upload-status").textContent = error.message; }
    finally { element("upload").disabled = false; }
  };
  element("train").onclick = async () => {
    element("train").disabled = true;
    try { const status = await api("/api/devices/train", {job_id:activeJob}); display(status); await watch(status.job_id); }
    catch (error) { element("status").textContent = error.message; }
  };
  element("refresh").onclick = async () => {
    try {
      const result = await api("/api/devices/jobs");
      element("jobs").replaceChildren(new Option("选择任务", ""), ...result.jobs.map((job) => new Option(`${job.device_id} · ${job.state}`, job.job_id)));
    } catch (error) { element("status").textContent = error.message; }
  };
  element("jobs").onchange = async () => {
    if (!element("jobs").value) return;
    watching = null;
    try { const status = await api(`/api/devices/status?job_id=${element("jobs").value}`); display(status); if (status.state === "training") await watch(status.job_id); }
    catch (error) { element("status").textContent = error.message; }
  };
  api("/api/manifest").then((value) => {
    element("model").textContent = value.device_onboarding_available ? `共享模型：${value.model_label}` : "当前模型不支持新设备训练，请加载32全数据发布权重。";
    element("upload").disabled = !value.device_onboarding_available;
  }).catch((error) => { element("model").textContent = error.message; });
})();
