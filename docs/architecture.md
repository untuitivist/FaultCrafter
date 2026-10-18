# Application architecture

The CLI and the local browser GUI use `faultcrafter.services.application.RuntimeApplication`. The service owns model identity, request conversion, generation, batch jobs and device registration. The GUI owns HTTP routing and presentation; it does not implement a second generator.

```text
faultcrafter/
  cli.py, __main__.py       command-line interface
  services/                application, batch and device job services
  gui/server.py            loopback HTTP interface
  gui/assets/              packaged HTML and JavaScript
  training/objectives.py   reusable training objective
  resources/               versioned device-training recipe
  data/                    record types and dataset adapters
  *.py                     model, conditioning and signal-processing modules
tests/                     product contract and integration checks
desktop/                   optional Windows packaging
examples/                  generation requests
tools/export_source.py     code-only repository export
```

`compact_deployment.py` loads the shared generator, the selected device LoRA and its signal profile. The profile describes the sensor, channel, sampling rate, fault identities and physical condition fields. Condition statistics folded into release32's LoRA are not an additional inference file. Model architecture and sampling settings remain those declared by the loaded package.

Model weights and writable device/job data have separate roots. `FAULTCRAFTER_MODEL_ROOT` or `--model-root` selects the model package; `FAULTCRAFTER_DATA_ROOT` or `--user-data-root` selects writable state. A source checkout retains its existing local paths. An installed wheel uses the operating system's user state directory and does not depend on the working directory.

Both frontends use the same unit conversions and input validation. Custom backbones receive separate default user state keyed by their shared-model hash; release32 retains its existing device registry. Explicit data roots are validated against the selected backbone. A compute lock serializes threads and rejects competing processes that share the same user-data root. Training and generation in separate user-data roots remain separate application instances; allocate their compute resources explicitly.

The model inspection path does not load raw training records or change existing job states. LoRA training imports the packaged training objective, not a script from the research workspace. Model files are loaded with `weights_only=True` and shared-model hashes bind the LoRA and signal identity to the selected backbone.

The GUI binds to `127.0.0.1`. This release is a local application, with no multi-user authentication or remote job scheduler. Production acceptance also needs environment-specific installation, performance and recovery checks. Experiment outcomes and diagnostic usefulness are evaluated separately from these software checks.
