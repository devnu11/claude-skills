"""``python -m unattended``: the detached supervisor runs this way."""

import sys

from .cli import main

sys.exit(main())
