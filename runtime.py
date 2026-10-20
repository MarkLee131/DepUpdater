"""Resource limits shared by the CLI and spawned analysis workers."""
import math
import os


def default_workers():
    # Each candidate can launch a JVM; CPU count alone is too aggressive.
    return min(4, max(1, os.cpu_count() or 1))


def worker_count(task_count):
    requested = int(os.environ.get('DEPUPDATER_WORKERS', default_workers()))
    if requested < 1:
        raise ValueError('DEPUPDATER_WORKERS must be positive')
    return min(requested, max(1, task_count))


def analyzer_timeout():
    seconds = float(os.environ.get('DEPUPDATER_ANALYZER_TIMEOUT', '300'))
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('DEPUPDATER_ANALYZER_TIMEOUT must be finite and positive')
    return seconds
