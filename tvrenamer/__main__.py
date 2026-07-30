"""Allow running tvrenamer as a package: python -m tvrenamer"""

import sys
from .cli import main

sys.exit(main())
