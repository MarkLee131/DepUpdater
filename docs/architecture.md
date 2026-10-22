# Repository layout

The `main` branch separates runtime code, bundled analyzers, study records, and
website content. The original `artifact` branch and its pinned links retain
their published layout.

```text
depupdater/
  __main__.py              # python -m depupdater
  cli.py                   # arguments and isolated run lifecycle
  paths.py                 # repository resources and per-run output paths
  runtime.py               # worker limits and analyzer timeouts
  analysis/                # compatibility checks, candidates, cache, validation
  preprocessing/           # project copying, Maven commands, graph restoration
  graph/                   # dependency traversal and graph updates
  database/                # MongoDB/SQLite access and dependency metadata
  metrics/                 # dependency counts and technical lag
  log.py                   # analysis logging
tools/
  analyzers/               # original JARs and complete Revapi distribution
  java/                    # SortVersions.java (Maven ComparableVersion bridge)
research/
  results/rq1/             # tool comparison CSVs
  results/rq2/             # ablation CSVs
  results/rq3/             # transitive dependency impact CSVs
  baselines/               # historical evaluation scripts
tests/                     # offline regression suite
docs/                      # usage, maintenance, and migration documentation
  design/                  # editable social preview and supplied template
assets/                    # website CSS, JavaScript, fonts, images, and BibTeX
_data/                     # author names, links, and photo provenance
index.html                 # Jekyll homepage
_config.yml                # Pages configuration and pinned research links
compose.yml                # local MongoDB service
MainProcess.py             # compatibility launcher
requirements.txt           # pinned Python dependencies
```

## Commands and paths

Run `python -m depupdater` from the checkout. `python MainProcess.py` continues
to delegate to the same CLI, with the same arguments and exit codes; it can also
be invoked by absolute path from another working directory. Neither entry point
starts an analysis when imported. This repository is run from a checkout; the
Java binaries are external resources, not an installable Python wheel payload.

All analyzer and database locations derive from `depupdater.paths.PROJECT_ROOT`,
not the shell's working directory. The snapshot `reusable_data.sqlite`, shared
`data/jar/` cache, and `data/verified_analysis.sqlite` remain in their existing
locations. Per-run outputs and the `DEPUPDATER_*` environment variables retain
their existing behavior. Existing snapshots do not need to be moved.

Use `docker compose -f compose.yml up -d` for MongoDB. The two BSON files remain
at the repository root, as described in [setup](setup.md).

## Renamed modules

| Previous location | Current location |
| --- | --- |
| `MainProcess.py` implementation | `depupdater/cli.py` |
| `constants.py` | `depupdater/paths.py` |
| `runtime.py` | `depupdater/runtime.py` |
| `computation/` | `depupdater/analysis/` |
| `computation/computation.py` | `depupdater/analysis/candidates.py` |
| `computation/analysis_cache.py` | `depupdater/analysis/cache.py` |
| `preprocess/Restore.py` | `depupdater/preprocessing/restore.py` |
| `preprocess/exec_maven_command.py` | `depupdater/preprocessing/maven.py` |
| `preprocess/multiModule.py` | `depupdater/preprocessing/modules.py` |
| `traverse/traverse.py` | `depupdater/graph/traversal.py` |
| `update/updateDG.py` | `depupdater/graph/update.py` |
| `update/updateDB.py` | `depupdater/database/populate.py` |
| `update/download_pom.py` | `depupdater/database/download_pom.py` |
| `database/constants.py` | `depupdater/database/config.py` |
| `evaluation/dep_count.py` | `depupdater/metrics/dependency_count.py` |
| `evaluation/tech_lag.py` | `depupdater/metrics/technical_lag.py` |
| `logger/logger.py` | `depupdater/log.py` |
| `Dependabot.py` | `research/baselines/dependabot.py` |

Python modules use lowercase snake_case names and imports start with
`depupdater`. Third-party analyzer filenames and Maven's bundled repository
layout are preserved. The Java helper keeps its required class filename.

Research result files have descriptive lowercase names; their contents are
unchanged. Historical baseline scripts preserve study-specific paths and
assumptions and are not part of the supported analysis CLI. See
[research notes](research-results.md) for the published data and
[reliability notes](reliability.md) for behavior changes from the artifact.

## Validation

Run `python -m unittest discover -s tests -v`. The suite exercises failures,
workspace preservation, Maven ordering, multiprocessing with spawn, storage,
and resource paths. It does not require database snapshots or a running MongoDB
server. Full experiment reproduction still requires the pinned artifact and
its documented environment.
