import logging
from pathlib import Path

from PIL import Image
from natsort import natsort_keygen, ns

from .config import ENV
from .util import read_metadata, get_type, get_mime


class Album:
    """
    Get information on an album (directory).

    Provides several attributes:
        url: url str
        meta: dict
        thumbnail: url str
        albums: list of sub-albums
        images: list
        videos: list
        files: list

    albums, images, videos, and files are sorted as specified.

    Args:
        path: album file path
        prefix: web prefix to add to media paths (for editing)
    """
    def __init__(self, path: Path, prefix: Path | None = None):
        logging.info('reading album %s', path)
        basedir = Path(ENV.SOURCE)
        web_prefix = prefix if prefix else Path('/')

        self.url = str(web_prefix / path.relative_to(basedir))
        self.meta = read_metadata(path)
        if not self.meta['title']:
            self.meta['title'] = path.name
        self.albums = []
        self.images = []
        self.videos = []
        self.files = []

        for child in path.iterdir():
            if child.name == 'thumbnails' or child.name.endswith('.meta.json'):
                pass
            elif child.is_dir():
                self.albums.append(AlbumItem(child, prefix=prefix))
            else:
                data = Media(child, prefix=prefix)
                if data.type == 'image':
                    self.images.append(data)
                elif data.type == 'video':
                    self.videos.append(data)
                else:
                    self.files.append(data)

        sorting = self.meta.get('sort', 'filename')
        if 'filename' in sorting:
            logging.info('sort by filename')
            sort_key = natsort_keygen(
                key=lambda s: s.name, alg=ns.SIGNED|ns.LOCALE
            )
        elif 'meta.' in sorting:
            meta_key = sorting.split(".", 1)[1]
            logging.info('sort by meta %s', meta_key)
            sort_key = natsort_keygen(
                key=lambda s: s.meta.get(meta_key, ""), alg=ns.SIGNED|ns.LOCALE
            )
        else:
            sort_key = natsort_keygen(
                key=lambda s: s.name, alg=ns.SIGNED|ns.LOCALE
            )
            logging.warning('unknown sorting: %r', sorting)

        reverse_sort = sorting[0] == '-'
        if reverse_sort:
            logging.info('REVERSED sorting')

        self.albums.sort(key=sort_key, reverse=reverse_sort)
        self.images.sort(key=sort_key, reverse=reverse_sort)
        self.videos.sort(key=sort_key, reverse=reverse_sort)
        self.files.sort(key=sort_key, reverse=reverse_sort)

        if 'thumbnail' in self.meta:
            basedir = Path(ENV.SOURCE)
            self.thumbnail = str(Path('/_src') / path.relative_to(basedir) / self.meta['thumbnail'])
        else:
            self.thumbnail = get_thumbnail(path)


class AlbumItem:
    def __init__(self, path: Path, prefix: Path | None = None):
        basedir = Path(ENV.SOURCE)
        if not prefix:
            prefix = Path('/')

        self.url = str(prefix / path.relative_to(basedir))
        self.album_url = str(prefix / path.relative_to(basedir).parent) + '#' + path.name
        self.src =  str(Path('/_src') / path.relative_to(basedir))
        self.name = path.name
        self.type = 'album'

        self.meta = read_metadata(path)
        if not self.meta['title']:
            self.meta['title'] = path.name
        logging.debug('meta for %s = %r', path.name, self.meta)

        self.thumb(path)

    def thumb(self, path: Path):
        if 'thumbnail' in self.meta:
            basedir = Path(ENV.SOURCE)
            self.thumbnail = str(Path('/_src') / path.relative_to(basedir) / self.meta['thumbnail'])
        else:
            self.thumbnail = get_thumbnail(path)


class Media(AlbumItem):
    def __init__(self, path: Path, prefix: Path | None = None):
        logging.debug('reading media %s', path)
        super().__init__(path=path, prefix=prefix)

        if not prefix:
            prefix = Path('/_src')
        basedir = Path(ENV.SOURCE)

        # this may be a different prefix than AlbumItem
        self.url = str(prefix / path.relative_to(basedir))
        self.type = get_type(path)
        self.mime = get_mime(path)

        if self.type == 'image':
            self.width, self.height = get_image_size(path)

    def thumb(self, path: Path):
        if 'thumbnail' in self.meta:
            basedir = Path(ENV.SOURCE)
            self.thumbnail = str(Path('/_src') / path.relative_to(basedir).parent / self.meta['thumbnail'])
        else:
            self.thumbnail = get_thumbnail(path)


def get_image_size(path: Path) -> tuple[int, int]:
    try:
        return Image.open(str(path)).size
    except Exception:
        logging.info('cannot get size of image at %s', path)
        return (150, 150)


def get_thumbnail(path: Path) -> str:
    basedir = Path(ENV.SOURCE)
    if path.is_dir():
        ret = path / 'thumbnails' / 'thumb.jpg'
        if ret.exists():
            return '/_src/'+str(ret.relative_to(basedir))
        else:
            return '/static/echo/blank.gif'
    elif get_type(path) == 'image':
        ret = path.parent / 'thumbnails' / path.name
        if ret.exists():
            return '/_src/'+str(ret.relative_to(basedir))
        elif ret.with_suffix('.jpg').exists():
            return '/_src/'+str(ret.relative_to(basedir).with_suffix('.jpg'))
        else:
            return '/_src/'+str(path.relative_to(basedir))
    else:
        ret = path.parent / 'thumbnails' / path.name
        ret = ret.with_suffix('.jpg')
        if ret.exists():
            return '/_src/'+str(ret.relative_to(basedir))
        else:
            return '/static/echo/blank.gif'
