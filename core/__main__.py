"""Direct python module execution: python3 -m core ... or python3 /path/to/core/__main__.py"""

import sys
from pathlib import Path

# Ensure the parent directory containing the 'core' package is on sys.path
package_root = Path(__file__).resolve().parent.parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from core.cli import main

if __name__ == "__main__":
    sys.exit(main())
