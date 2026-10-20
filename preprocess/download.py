"""Download JARs without exposing incomplete cache entries to other workers."""
import os
from pathlib import Path
import tempfile
import time
import zipfile
import zlib

import requests


def valid_jar(path):
    try:
        with zipfile.ZipFile(path) as jar:
            return jar.testzip() is None
    except (OSError, zipfile.BadZipFile, RuntimeError, zlib.error):
        return False


def download_jar(url, destination, *, retries=3, backoff=0.3):
    """Reuse valid archives; publish downloads only after ZIP/CRC validation.

    Every attempt has a private temporary file next to the destination, so
    os.replace is atomic even when multiple workers request the same JAR.
    """
    if retries < 1:
        raise ValueError('retries must be positive')
    destination = Path(destination)
    if valid_jar(destination):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        temporary = None
        try:
            with requests.get(url, stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                with tempfile.NamedTemporaryFile(dir=destination.parent,
                                                 prefix=destination.name + '.', suffix='.part',
                                                 delete=False) as stream:
                    temporary = Path(stream.name)
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            stream.write(chunk)
                if not valid_jar(temporary):
                    raise zipfile.BadZipFile(f'Invalid JAR downloaded from {url}')
                os.replace(temporary, destination)
                return
        except (requests.RequestException, OSError, zipfile.BadZipFile):
            if attempt == retries - 1:
                raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        time.sleep(backoff * (2 ** attempt))
