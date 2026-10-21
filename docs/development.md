# Development and distribution

`faultcrafter.method_model.MethodGenerator` exposes the release32 backbone for fresh held-out research training. Its condition vector contains seven physical fields and seven independent presence masks, followed by device, channel, atomic fault indicators and sample rate. `load_method` accepts only explicitly eligible benchmark checkpoints; deployment packages are separate. LoRA adaptation updates new-route low-rank slices and new-device label rows while restoring every frozen parameter after AdamW and EMA. The independent [experiment repository](https://github.com/untuitivist/FaultCrafter-experiments) provides the training queue, data isolation audit and T1–T4 evaluation; these comparison modules do not belong in the method package.

Install the `training` and `dev` extras. The current product checks exercise input units, masks, signal analysis, compact-model identity, shared CLI/GUI behavior and device upload isolation:

```console
python -m pip install -e ".[training,dev]"
python -m pytest
node --test tests/test_condition_units_web.cjs
python -m build
```

Tests that require separately installed release weights skip when those weights are unavailable. Small generated fixtures check software contracts and are not benchmark results. Run release-weight inference as an additional acceptance check for each distributed model.

The wheel contains only the Python package, GUI resources and the device-training recipe. It excludes datasets, learned weights, user data, research archives, manuscripts and Agent records. Verify a wheel from a directory outside the checkout before releasing it.

Windows `desktop/FaultCrafter.spec` builds the browser application with an explicitly installed release32 package. Use `FAULTCRAFTER_PYTHON` to select the build interpreter and `FAULTCRAFTER_MODEL_ROOT` for an external compact package. The CPU requirements install CPU PyTorch and training support. These build recipes are separate from the already-built executables; rebuilding is required to update a distributed executable.

`tools/export_source.py --destination PATH` fills a new directory or an empty Git checkout using an explicit allowlist. It refuses existing working files, symlinks and large files. Its audit manifest is generated locally and ignored by Git. Inspect the exported tree before committing it to the public repository. Never push a research repository's historical commits just because its current `.gitignore` hides local artifacts.

The public repository's `.gitignore` uses an allowlist. Add a new source surface deliberately in both the ignore file and the export tool. Product documentation belongs under the three named `docs/` files; manuscripts and development-agent notes belong outside the public code tree.
