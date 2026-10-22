# Database setup

[Back to setup and usage](../README.md#usage)

These steps configure the `main` branch after installing the Python
requirements. Run the commands from the DepUpdater repository root. To reproduce
the published experiments, use the
[pinned artifact instructions](https://github.com/MarkLee131/DepUpdater/blob/163cf411da6047dbacb8340602314723d88b729b/README.md#usage)
and the corresponding experiment environment.

## 1. Download and extract the snapshots

Download all three archives from [Zenodo](https://zenodo.org/records/20340636):

| Archive | Extracted file needed | Used by |
| --- | --- | --- |
| [maven.zip](https://zenodo.org/records/20340636/files/maven.zip?download=1) | `maven.bson` | MongoDB `maven.maven` collection. |
| [maven_deps.zip](https://zenodo.org/records/20340636/files/maven_deps.zip?download=1) | `maven_deps.bson` | MongoDB `maven.maven_deps` collection. |
| [reusable_data.zip](https://zenodo.org/records/20340636/files/reusable_data.zip?download=1) | `reusable_data.sqlite` | SQLite artifact-location and dependency metadata. |

Place the extracted files directly in the repository root, not inside an extra
archive directory. The downloads total several gigabytes; allow additional space
for extracted snapshots, restored collections, JARs, and project working copies.

```text
DepUpdater/
├── MainProcess.py
├── docker-compose-mongodb.yml
├── maven.bson
├── maven_deps.bson
└── reusable_data.sqlite
```

Confirm that the three files exist **before starting Compose**, which mounts the
BSON files into the container:

```sh
ls -lh maven.bson maven_deps.bson reusable_data.sqlite
```

The SQLite snapshot is used directly; do not import it into MongoDB or replace it
with an empty database. The tool writes metadata during use, so retain clean
snapshot copies for independent experiments.

## 2. Start MongoDB

```sh
docker compose -f docker-compose-mongodb.yml up -d
docker exec maven_mongodb mongosh --quiet --eval 'db.adminCommand({ ping: 1 })'
```

If MongoDB is still starting, wait until the ping succeeds before restoring data.
For installations with the older standalone Compose command, use
`docker-compose` instead of `docker compose`.

The supplied [Compose file](../docker-compose-mongodb.yml) names the container
`maven_mongodb` and publishes port `27017`. The Python connection settings are
in [`database/constants.py`](../database/constants.py): `localhost:27017`.
The image is currently `mongo:latest`, not a pinned historical environment;
record the resolved MongoDB image/version for your runs. The supplied file does
not declare a named data volume, so retain the snapshots for container recreation.

## 3. Restore the collections

For a fresh setup, restore each BSON file once into the `maven` database:

```sh
docker exec maven_mongodb mongorestore \
  --db maven --collection maven /data/maven.bson

docker exec maven_mongodb mongorestore \
  --db maven --collection maven_deps /data/maven_deps.bson
```

Check both commands' restore summaries for failed documents. Re-running a restore
into populated collections is not a clean reset. For a partially restored setup,
inspect the restore errors before continuing.

These commands restore individual BSON files using
[MongoDB's `mongorestore` options](https://www.mongodb.com/docs/database-tools/mongorestore/).

## 4. Create indexes and verify the data

```sh
docker exec maven_mongodb mongosh maven --quiet --eval '
  db.maven.createIndex({ group: 1, artifact: 1 });
  db.maven.createIndex({ group: 1, artifact: 1, version: 1 });
  db.maven_deps.createIndex({ parent: 1 });
'
```

The first two are compound indexes; `parent` is a single-field index. These match
the metadata lookup fields used by the tool. See
[MongoDB's `createIndex` reference](https://www.mongodb.com/docs/manual/reference/method/db.collection.createindex/).

Check that both collections contain data and inspect their indexes:

```sh
docker exec maven_mongodb mongosh maven --quiet --eval '
  printjson({
    maven: db.maven.estimatedDocumentCount(),
    maven_deps: db.maven_deps.estimatedDocumentCount()
  });
  printjson(db.maven.getIndexes());
  printjson(db.maven_deps.getIndexes());
'
```

Nonzero counts are a basic setup check, not proof of a complete restoration;
check the restore summaries as well. Then continue with
[your first analysis](../README.md#3-analyze-a-project).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Cannot connect to MongoDB | Check `docker compose -f docker-compose-mongodb.yml ps`, run the ping above, and confirm port `27017` matches `database/constants.py`. |
| Missing SQLite snapshot | Confirm `reusable_data.sqlite` is in the repository root, not the target project's directory or an archive subfolder. |
| BSON path is a directory | Check that the source BSON files existed before Compose started. Correct the host paths and recreate the container mounts before restoring. |
| Original project does not build or test | Check the console output, required JDK, Maven repositories, profiles, and project configuration. DepUpdater validates the project before considering upgrades. |
| Analyzer times out | Inspect `error.txt` and the run's analysis logs. Consider `--workers 1` for resource pressure or a larger `--analyzer-timeout` for a long analyzer invocation. A timeout is a failed analysis, not evidence of compatibility. |
| Output directory already exists | Choose a new `--output` path outside the input project; previous runs are preserved. |
| Conflicting dependency metadata | Inspect the conflicting MongoDB records. The tool fails rather than deleting or arbitrarily choosing between conflicting dependency lists. |

Per-run output lives under `--output`. Shared JARs are stored in `data/jar/`, and
verified analyzer results in `data/verified_analysis.sqlite` by default. The
first run on `main` recomputes analyses instead of trusting the old
unverified analyzer cache. See [cache details](reliability.md#analyzer-failures-and-caching).
