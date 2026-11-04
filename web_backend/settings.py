"""Per-user settings; data never lives inside the application bundle."""
import json
import os
from pathlib import Path
import sys
from .result_cache import write_json

CONFIG = Path(os.environ.get('LOCALAPPDATA',Path.home()/'.config'))/'SUCURI'/'settings.json'

def default_storage():
    if sys.platform == 'win32' and Path('D:/').is_dir():
        return Path('D:/SUCURI')
    if sys.platform != 'win32' and Path('/mnt/d').is_dir():
        return Path('/mnt/d/SUCURI')
    return Path.home()/'SUCURI'

def storage_path():
    try:
        return Path(json.loads(CONFIG.read_text(encoding='utf-8'))['storage']).expanduser().resolve()
    except (OSError,ValueError,KeyError,TypeError):
        return default_storage()

def save_storage(path):
    path=Path(path).expanduser().resolve()
    path.mkdir(parents=True,exist_ok=True)
    write_json(CONFIG,{'storage':str(path)})
    return path
