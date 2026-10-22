# Reliability notes

[Back to the README](../README.md#reliability-improvements)

Reliability fixes are developed on `main`. The `artifact` branch at
`163cf41` is the unchanged starting point for this work. Use the original
artifact code, its database snapshots, and its experiment configuration when
reproducing the published experiments. Results from this branch are not
automatically equivalent: corrected analysis failures and version ordering can
change recommendations and technical-lag counts.

## Working-copy isolation

The CLI now analyzes a separate copy of the **current working tree**, including
uncommitted and untracked files. It does not stash, reset, or edit the input
project. Git metadata in the copy is independent of the original repository.
Project symlinks are materialized as copies. Build configurations that refer to
absolute external paths still require project-specific configuration; this is
workspace isolation, not an operating-system sandbox.

```shell
python MainProcess.py -r /path/to/project -m module-a --output /path/to/new-run
```

## Resource controls

Use `--workers N` to limit candidate analysis and dependency preprocessing. The
default is `min(4, CPU count)`, capped again by the number of tasks; `--workers 1`
runs these stages in the main process. Pruned candidates are not submitted to the
analyzer pool. Each analyzer worker receives the graph once, and at most twice
the worker count of tasks are queued. Results retain candidate/dependency order.

Use `--analyzer-timeout SECONDS` to adjust the per-invocation timeout for Revapi,
Soot, and BCEL (default: 300). Both settings are recorded in `run.json` and
inherited by spawned workers. Increasing the timeout does not rerun an already
successful cached analysis. Active tasks finish or hit their own timeout before
an executor shuts down after a failure; queued tasks are cancelled.

```shell
python MainProcess.py -r /path/to/project -m module-a --workers 2 --analyzer-timeout 600
```

## Outputs and exit codes

`--output` must be a new directory outside the input project. Without it, a
temporary directory is created and its path is printed. The directory is kept
on success, failure, and interruption for inspection:

```text
new-run/
├── run.json                 # source, workspace, ordering policy, status, exit code
├── error.txt                # traceback if an exception occurs
├── workspace/<project>/     # independent project copy and build outputs
└── analysis/                # dependency graphs, logs and lag.csv
```

After traversal, the selected module's `pom.xml` in the workspace is restored.
`_original_pom.xml` contains its original bytes; `_backed_up_pom.xml` contains
the candidate POM. On failure this candidate may be incomplete or unvalidated;
check `run.json` and the build/test logs before using it. The input POM stays
unchanged. Interrupted runs return `130`, invalid CLI arguments return `2`, and
analysis/build/test failures return `1`; successful runs return `0`.

## Version ordering and technical lag

Version ordering defaults to Maven's `ComparableVersion`, using the pinned
`maven-artifact-3.6.2.jar` already bundled with Revapi and the source helper
`utils/SortVersions.java`. The JDK runs this helper directly; no extra download
is needed. Maven-equivalent spellings use lexical order as a deterministic tie
breaker. Publication timestamps do not influence this order. Technical lag
continues to count positions in the filtered candidate-version list, so changing
that list's ordering can change the metric.

`--version-order legacy` preserves the original SemVer/date comparator **for
comparison only**, including its known inconsistent ordering. It does not
disable the other reliability fixes or restore artifact-era cache behavior.
Maven ordering follows the [Maven version comparison implementation](https://maven.apache.org/ref/3.6.2/maven-artifact/apidocs/org/apache/maven/artifact/versioning/ComparableVersion.html).

## Analyzer failures and caching

Revapi, Soot, and BCEL must exit successfully before their output is used.
Timeouts (300 seconds by default), missing artifacts, and nonzero
exit codes abort analysis instead of being interpreted as compatibility. BCEL
diagnostics on stderr also abort: its bundled tools may exit zero after a parsing
error. Valid empty output is distinct from failure. Verified results are cached in
`data/verified_analysis.sqlite`, keyed by command, analyzer namespace, and input
and tool content hashes. Set `DEPUPDATER_ANALYSIS_CACHE` to use another path.
Legacy analysis entries in `reusable_data.sqlite` are not trusted because they
have no execution status; the first run on this branch will therefore recompute
those analyses. The existing artifact-location and dependency-metadata databases
are still required. Use separate working copies of datasets for independent
experiments.

## Downloads and database integrity

JAR downloads are streamed into private temporary files, checked as ZIP archives
including entry CRCs, and then atomically moved into the cache. Interrupted or
invalid downloads never publish a partial JAR. Existing corrupt archives are
downloaded again. SQLite operations now propagate database errors, close their
connections on all exits, and commit related writes together or roll them back.
A missing snapshot is an error rather than an implicitly created empty database.
MongoDB reads preserve duplicate records: identical dependency lists are usable;
conflicting lists raise an error and require explicit data repair.

## Regression checks

Run the offline regression suite after installing the requirements and a JDK:

```shell
python -m unittest discover -s tests -v
```

The suite covers working-tree/stash preservation, analyzer failure and timeout
handling, empty-result caching, POM scope and restoration, deterministic Maven
ordering, import-safe CLI behavior, failure exit codes, real spawn-process
execution, serial/parallel equivalence, transaction rollback, and interrupted
and concurrent downloads. It does not require
MongoDB, downloaded experiment datasets, or network access and does not replace
the full published experiment reproduction.
