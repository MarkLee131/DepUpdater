"""Cache successful analyzer output separately from unverified artifact-era data."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from computation.execution import run_checked


def run_cached(command, *, files, namespace, timeout=300, reject_stderr=False):
    """Cache only exit-code-zero executions, including genuinely empty output.

    Hash input artifacts and analyzer binaries so changing a local JAR or an
    analyzer cannot silently reuse a previous result. Never read legacy tables:
    those tables do not distinguish execution failures from empty results.
    """
    fingerprints = []
    for file in files:
        digest = hashlib.sha256()
        with open(file, 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        fingerprints.append(digest.hexdigest())
    key = hashlib.sha256(json.dumps(
        [namespace, command, fingerprints, reject_stderr], sort_keys=True,
    ).encode()).hexdigest()
    default = Path(__file__).resolve().parents[1] / 'data' / 'verified_analysis.sqlite'
    path = Path(os.environ.get('DEPUPDATER_ANALYSIS_CACHE', str(default)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=30)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS successful_analysis '
                   '(cache_key TEXT PRIMARY KEY, output TEXT NOT NULL)')
        row = db.execute('SELECT output FROM successful_analysis WHERE cache_key=?', (key,)).fetchone()
        if row is not None:
            return row[0]
    output = run_checked(command, timeout=timeout, reject_stderr=reject_stderr)
    with closing(sqlite3.connect(path, timeout=30)) as db:
        with db:
            db.execute('INSERT OR REPLACE INTO successful_analysis VALUES (?, ?)', (key, output))
    return output
