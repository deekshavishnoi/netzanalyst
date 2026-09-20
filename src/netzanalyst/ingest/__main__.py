"""Allow `python -m netzanalyst.ingest` as well as the console script."""

import sys

from netzanalyst.ingest.smard import main

if __name__ == "__main__":
    sys.exit(main())
