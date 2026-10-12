import sys
from hub_platform.cli import main

sys.stdout.reconfigure(encoding="utf-8")
raise SystemExit(main())
