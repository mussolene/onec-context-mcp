"""Bootstrap entry point for ``python -m onec_help.cli``."""

from .interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
