"""Allow running as: python -m eab"""
import sys
from .daemon import main

if __name__ == "__main__":
    sys.exit(main())
