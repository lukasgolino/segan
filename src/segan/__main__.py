"""Allow running SEGAN as `python -m segan`."""

import sys

from segan.cli import main

sys.exit(main())
