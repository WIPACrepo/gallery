from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .config import ENV


def now() -> datetime:
    return datetime.now(timezone.utc)


def get_type(path: Path) -> str:
    ext = path.suffix
    if not ext:
        return 'file'
    ext = ext[1:].lower()
    if ext in ENV.IMG_EXTENSIONS:
        return 'image'
    elif ext in ENV.VIDEO_EXTENSIONS:
        return 'video'
    else:
        return 'file'


MIME_TYPES = {
    # image mimes
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.png': 'image/png',
    # video mimes
    '.avi': 'video/x-msvideo',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.ogv': 'video/ogg',
    '.3gp': 'video/3gpp',
}


def get_mime(path: Path) -> str:
    ext = path.suffix
    return MIME_TYPES.get(ext, 'application/octet-stream')


def read_metadata(path: Path) -> dict[str, Any]:
    if path.is_dir():
        path = path / 'index.meta.json'
    else:
        path = path.with_suffix('.meta.json')

    ret = {'title': '', 'keywords': '', 'summary': '', 'description': ''}
    if path.exists():
        with open(path) as f:
            ret.update(json.load(f))
    return ret


def write_metadata(path: Path, data: dict[str, Any]):
    if path.is_dir():
        path = path / 'index.meta.json'
    else:
        path = path.with_suffix('.meta.json')

    ret = {'title': '', 'keywords': '', 'summary': '', 'description': ''}
    ret.update(data)
    with open(path, 'w') as f:
        json.dump(ret, f, ensure_ascii=False, indent=2)
