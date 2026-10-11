"""Run phantom-deps as a module: python -m phantom_deps."""
from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
