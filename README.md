# FaultCrafter

FaultCrafter generates one-dimensional vibration signals for specified fault identities and operating conditions. It provides a command-line interface and a local browser GUI, backed by the same Python services.

A deployed model uses a shared generator, one LoRA for the selected device, and a signal profile describing the sensor, channel and physical inputs. Generation does not require source recordings. New-device adaptation uses the supplied training and validation records.

## Install and run

Python 3.11 or newer is required. Install a suitable PyTorch build for your CPU or GPU, then:

```console
python -m pip install -e ".[training]"
faultcrafter --help
faultcrafter inspect --model-root /path/to/compact
faultcrafter gui --model-root /path/to/compact
```

`python -m faultcrafter` is equivalent to the console command. Model weights are installed separately. Set `FAULTCRAFTER_MODEL_ROOT` to avoid repeating the model path.

```console
faultcrafter generate --request examples/generate.json --output generated/signal.json
faultcrafter batch --request examples/batch.json --output generated/batch.zip
```

The examples use the BJTU route in the full-data release32 package. Inspect your package for its actual device, fault and condition identifiers.

## Code layout

| Path | Responsibility |
|---|---|
| `faultcrafter/services/` | Shared generation, batch and device-adaptation services |
| `faultcrafter/gui/` | Local HTTP interface and packaged browser assets |
| `faultcrafter/training/` | Reusable training objective |
| `faultcrafter/resources/` | Versioned adaptation recipe |
| `tests/` | Product behavior and integration checks |
| `examples/` | CLI request examples |
| `desktop/` | Optional Windows executable build |
| `tools/export_source.py` | Audited code-only export |

The public code repository excludes raw datasets, weights, user uploads, experiment outputs, manuscripts and Agent notes. The local research workspace and paper are maintained separately.

## Documentation

- [Usage and new-device adaptation](docs/usage.md)
- [Architecture and deployment boundaries](docs/architecture.md)
- [Development and packaging](docs/development.md)

The current application supports local use. Model quality and extrapolation accuracy depend on the trained package and evaluation protocol; repository installation checks are separate from scientific benchmark results.

## License

[MIT](LICENSE). Dataset and model distribution permissions are handled separately from the code license.
