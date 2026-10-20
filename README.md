# ![DepUpdater](img/DepUpdater.ico) Minimizing Breaking Changes and Redundancy in Mitigating Technical Lag for Java Projects
[![arXiv](https://img.shields.io/badge/arXiv-<2511.06762>-<COLOR>.svg)](https://arxiv.org/abs/2511.06762)  [![](https://img.shields.io/badge/ICSE-2026-red?style=flat-square)](https://conf.researchr.org/home/icse-2026)


## Abstract 
Re-using open-source software (OSS) can avoid reinventing the wheel, but failing to keep it up-to-date can lead to missing new features and persisting bugs or vulnerabilities that have already been resolved. The use of outdated OSS introduces technical lag,
necessitating timely upgrades. However, maintaining up-to-date libraries is challenging, as it may introduce compatibility issues that break the project or add redundant dependencies. These issues discourage developers from upgrading libraries, highlighting the
need for a fully automated solution that balances version upgrades, reduces technical lag, ensures compatibility, and prunes redundant dependencies.

To this end, we propose DepUpdater, which ensures that upgrades minimize technical lag as much as possible while avoiding compatibility issues and redundant dependencies. The comparison with existing dependency management tools demonstrates that DepUpdater more effectively reduces technical lag while ensuring compatibility and pruning redundant dependencies. Additionally, an ablation study highlights the potential benefits of considering pruning requirements during upgrades to mitigate compatibility issues. Finally, leveraging DepUpdater, we investigate the impact of transitive dependency upgrades on client compatibility, providing insights for future research.

![image](img/overview.png)

## Reliability branch

Reliability fixes are developed on `fix/reliability`. The `artifact` branch at
`163cf41` is the unchanged starting point for this work. Use the original
artifact code, its database snapshots, and its experiment configuration when
reproducing the published experiments. Results from this branch are not
automatically equivalent: corrected analysis failures and version ordering can
change recommendations and technical-lag counts.

The CLI now analyzes a separate copy of the **current working tree**, including
uncommitted and untracked files. It does not stash, reset, or edit the input
project. Git metadata in the copy is independent of the original repository.
Project symlinks are materialized as copies. Build configurations that refer to
absolute external paths still require project-specific configuration; this is
workspace isolation, not an operating-system sandbox.

```shell
python MainProcess.py -r /path/to/project -m module-a --output /path/to/new-run
```

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

JAR downloads are streamed into private temporary files, checked as ZIP archives
including entry CRCs, and then atomically moved into the cache. Interrupted or
invalid downloads never publish a partial JAR. Existing corrupt archives are
downloaded again. SQLite operations now propagate database errors, close their
connections on all exits, and commit related writes together or roll them back.
A missing snapshot is an error rather than an implicitly created empty database.
MongoDB reads preserve duplicate records: identical dependency lists are usable;
conflicting lists raise an error and require explicit data repair.

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

## Usage

### Requirements

**1.** JDK 17

**2.** Maven 3.9.5

**3.** python 3.10.12

**4.** Ubuntu 2020

**5.** Necessary python packages :

* Install a virtual environment

```shell
python -m venv .venv
```

* Active the virtual environment

```bash
source .venv/bin/activate
```

* Install the required packages

```shell
pip install -r requirements.txt
```

**6.** A MongoDB docker container :

* Download `maven_deps.zip`  from https://zenodo.org/records/20340636/files/maven_deps.zip?download=1, then unzip it to get `maven_deps.bson`. (maven_des.zip is 2.42GB)
* Download `maven.zip` from https://zenodo.org/records/20340636/files/maven.zip?download=1, then unzip it to get `maven.bson`.
* Place `maven_deps.bson` and `maven.bson` at the root directory of this repository.
* Activate a MongoDB docker container named `maven_mongodb`.

```shell
docker-compose -f docker-compose-mongodb.yml up -d
```

* Restore two collections of the MongoDB :

restore the `maven` collection

```shell
docker exec maven_mongodb mongorestore --db maven --collection maven /data/maven.bson
```

retore the `maven_deps` collection

```shell
docker exec maven_mongodb mongorestore --db maven --collection maven_deps /data/maven_deps.bson
```

* Create indexes on the two collections 

Add two compound indexes to the `maven` collection: (`group`, `artifact`) and (`group`, `artifact`, `version`).

Add one compound index to the `maven_deps` collection: `parent`.

**7.** A `Sqlite`  database :

* Download `reusable_data.zip` from https://zenodo.org/records/20340636/files/reusable_data.zip?download=1, then unzip it to get `reusable_data.sqlite`.
* Place `reusable_data.sqlite` at the root directory of this repository.



### Run `DepUpdater`

Execute the MainProcess.py:

```
python MainProcess.py -h
usage: MainProcess.py [-h] -r ROOT -m MODULE [-j JAR]
                      [-l LOCAL_DEP_JAR [LOCAL_DEP_JAR ...]] [--output OUTPUT]
                      [--version-order {maven,legacy}] [--workers WORKERS]
                      [--analyzer-timeout ANALYZER_TIMEOUT]

options:
  -h, --help            show this help message and exit
  -r ROOT, --root ROOT  the path to the cloned folder
  -m MODULE, --module MODULE
                        the relative path to the module
  -j JAR, --jar JAR     the relative path to the client jar
  -l LOCAL_DEP_JAR [LOCAL_DEP_JAR ...], --local_dep_jar LOCAL_DEP_JAR [LOCAL_DEP_JAR ...]
                        the relative paths to the local module jar depended by client
  --output OUTPUT       new output directory outside the input project
  --version-order {maven,legacy}
                        Maven ordering by default; legacy comparator for comparison
  --workers WORKERS     maximum candidate/preprocessing workers; 1 runs serially
  --analyzer-timeout ANALYZER_TIMEOUT
                        timeout per Revapi/Soot/BCEL invocation in seconds
```

the `ROOT` and `MODULE` parameters are necessary, while `JAR` and `LOCAL_DEP_JAR` parameters are optional.

An example usage:

```shell
python MainProcess.py -r /home/test/mall -m mall-common
```

The `mall` repository is cloned from https://github.com/macrozheng/mall.git, and mall-common is a module of this repository.
`/home/test/mall` is the local location of the cloned repository, and `mall-common` is the relative path of the mall-common module.

## Source code structure

The structure of this repository is as follows:

```
.
├── computation # upgrade a dependency
├── constants.py # constants
├── database # query and update the Mongodb and sqlite
├── docker-compose-mongodb.yml # docker file
├── evaluation # compute reduced tech lag and dep count
├── logger # generate log
├── MainProcess.py # main function
├── maven.bson # maven collection
├── maven_deps.bson # maven_deps collection
├── preprocess # restore the dependency graph
├── README.md
├── requirements.txt # necessary pagckages
├── reusable_data.sqlite # splite file
├── RQs_data # data of RQs
├── traverse # traverse the dependency graph
└── update # update the database as well as the graph
```

## Data for RQs

Data for RQs is in the `RQs_data` folder, the structure of this folder is as follows:

```
.
├── RQ1
│   ├── RQ1_Dependabot.csv # Dependabot in RQ1
│   ├── RQ1_DepUpdater.csv # DepUpdater in RQ1
│   └── RQ1_Snyk.csv # Snyk in RQ1
├── RQ2
│   ├── RQ2_Compatibility_Only.csv # Compatibility only in RQ1
│   ├── RQ2_Pruning_Only.csv # Pruning only in RQ1
│   └── RQ2_Naive.csv # Naive in RQ1
└── RQ3
    ├── RQ3_API_Distribution.csv # Distribution of client-impacting API
    └── RQ3_Client_Distribution.csv # Distribution of Broken-Client
```

## For Major Revision

We appreciate the suggestions in the Metareview and Review A to provide the data at the project level. We applied the data from different tools to each project as follows:

![Extend_Table](img/RQ1_Extend_Table.png)

Note: 
1. Because Dependabot and Snyk do not consider pruning during the upgrades, they often introduce redundant dependencies, which can increase overall technical lag. For example, Dependabot increased the total version lag by 150 versions for the Netty project.
2. We have not listed the data for GoblinUpdater above, **as all of its data points are zero**.
3. After upgrades by Dependabot, three projects (Apollo, Jenkins, Druid) were unable to generate a dependency tree. After upgrades by Snyk, two projects (Sentinel, Jenkins) could not generate a dependency tree. Since we compute technical lag based on the dependency tree, we have listed the data for these projects as N/A.



## Pull Requests to Upgrade Dependencies


| Repository                                                   | PR                                                           | Stars | Compilation | Regression Test | Status    | Note |
| ------------------------------------------------------------ | ------------------------------------------------------------ | ----- | --------------------- | --------- | --------- | --------- |
| [easyexcel](https://github.com/alibaba/easyexcel)            | [#4123](https://github.com/alibaba/easyexcel/pull/4123)      | 33.5k |  &#10004;| &#10004; | submitted |  |
| [spring-cloud-alibaba](https://github.com/alibaba/spring-cloud-alibaba) | [#4023](https://github.com/alibaba/spring-cloud-alibaba/pull/4023) | 28.6k | &#10004; | &#10004; | submitted |  |
| [dubbo](https://github.com/apache/dubbo)                     | [#15577](https://github.com/apache/dubbo/pull/15577)                                                       | 41.2k | &#10004; | &#10004; | wont fix | The project maintains the same dependency versions across all modules, which is unrelated to our tool.|
| [Sentinel](https://github.com/alibaba/Sentinel)                                             | [#3536](https://github.com/alibaba/Sentinel/pull/3536)                                                  | 22.8k | &#10004; | &#10004; | merged | The maintainer upgraded the dependencies after review our PR. |
| [WxJava](https://github.com/binarywang/WxJava)                                                       | [#3643](https://github.com/binarywang/WxJava/pull/3643)                                                        | 31.6k | &#10004; | No tests in this module | merged | The maintainer upgraded the dependencies after review our PR. |



Stay informed about our ongoing efforts! 🤖

---


> [!IMPORTANT]
>
> Feel free to share your suggestions for this process by opening issues or PRs. :)
