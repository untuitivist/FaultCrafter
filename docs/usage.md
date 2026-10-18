# Using FaultCrafter

Install Python3.11 or newer and a PyTorch build suitable for the machine. From this repository:

```console
python -m pip install -e ".[training]"
faultcrafter --help
faultcrafter inspect --model-root /path/to/compact
faultcrafter gui --model-root /path/to/compact --port 8765
```

Model weights are installed separately. A compact package contains:

```text
compact/
  shared_generator.pt
  DEVICE_ID/
    device_lora.pt
    signal_profile.json
```

Use `inspect` to obtain the actual device IDs, fault IDs, condition names and supported units. Set `FAULTCRAFTER_MODEL_ROOT` to reuse a package across commands. If the package is missing, the application reports the missing path and does not select another model automatically.

Single-signal and batch commands accept the same JSON fields as the GUI service:

```console
faultcrafter generate --model-root /path/to/compact --request examples/generate.json --output generated/signal.json
faultcrafter batch --model-root /path/to/compact --request examples/batch.json --output generated/batch.zip
```

The examples target the BJTU route in the full-data release32 package. Adapt their identifiers and condition fields for another device. Single-signal JSON includes both normalized and physical waveforms, the random seed, model identity, condition conversion and signal analyses. Batch ZIP files contain per-signal CSVs and a manifest. Existing output files are not overwritten. CLI failures return a nonzero exit code and a JSON error on stderr.

For a new device, install the training extra, provide a `faultcrafter_device_upload_v1` manifest and separate training and validation recordings. The GUI's `/onboarding` page uses the same workflow:

```console
faultcrafter device prepare --model-root /path/to/compact --manifest upload.json --signals /path/to/recordings
faultcrafter device train JOB_ID --model-root /path/to/compact
faultcrafter device status JOB_ID --model-root /path/to/compact
```

`prepare` copies declared records into a job directory and validates their dimensions, physical conditions and train/validation content separation. `train` blocks until adaptation and export finish. It freezes release32's shared backbone and learns the new device LoRA. A successful registration makes the device available to the next CLI invocation; restart another already-running GUI instance to reload its device list.

Use a consistent `--user-data-root` across the commands. Preserve that directory to retain uploaded data, job logs and learned adapters. Training jobs run in the serving process and require it to remain alive; automatic crash recovery and resume are not provided in this version.

For Windows batch automation:

```bat
set FAULTCRAFTER_MODEL_ROOT=C:\models\faultcrafter\compact
set FAULTCRAFTER_DATA_ROOT=C:\work\faultcrafter
python -m faultcrafter device train JOB_ID > training.log 2>&1
```
