"""SUCURI local service; optional dependencies installed inside the workspace."""
from pathlib import Path
import sys
_vendor = Path(__file__).resolve().parents[1] / '.runtime' / 'python'
if sys.platform == 'win32' and sys.version_info[:2] == (3, 9) and _vendor.is_dir():
    sys.path.insert(0, str(_vendor))
