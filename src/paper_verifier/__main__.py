"""Entry point for ``python -m paper_verifier``."""
from __future__ import annotations

import sys

from paper_verifier.verify import main

if __name__ == "__main__":
    sys.exit(main())
