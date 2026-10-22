"""Compatibility launcher; new commands can use ``python -m depupdater``."""
from depupdater.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
