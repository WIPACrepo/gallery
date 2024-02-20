from functools import lru_cache
from pathlib import Path

from bs4 import BeautifulSoup
from sigal.utils import read_markdown as sigal_read_markdown


@lru_cache(maxsize=10)
def get_html(path):
    with open(path) as f:
        return BeautifulSoup(f, 'html.parser')


class SigalMixin:
    """
    Adds some helper functions using sigal settings.

    Assumes `self.sigal_settings` exists.
    """
    def _get_type(self, path):
        ext = path.suffix
        if not ext:
            return 'file'
        ext = ext.lower()
        if ext in self.sigal_settings['img_extensions']:
            return 'image'
        elif ext in self.sigal_settings['video_extensions']:
            return 'video'
        else:
            return 'file'

    def _get_pswp_hash(self, path):
        """Get a photoswipe hash for a media file"""
        if path.startswith('/'):
            path = path[1:]
        orig_name = Path(path).name
        album_html = (Path(self.sigal_settings['destination']) / path).parent / 'index.html'
        try:
            soup = get_html(album_html)
        except FileNotFoundError:
            return ''

        galleries = soup.find_all('div', 'gallery_pswp')
        for gid,gallery in enumerate(galleries):
            for pid,figure in enumerate(gallery.find_all('figure')):
                if figure.get('data-orig') == orig_name:
                    return f'#&gid={gid+1}&pid={pid+1}'
        return ''


def read_markdown(path):
    if path.is_dir():
        path = path / 'index.md'
    else:
        path = path.with_suffix('.md')
    ret = {'title': '', 'keywords': '', 'summary': '', 'description': '', 'meta': {}}
    if path.exists():
        ret.update(sigal_read_markdown(path))
        for k in ('thumbnail', 'summary', 'title', 'keywords', 'user'):
            if k in ret['meta']:
                ret[k] = str(ret['meta'][k][0])
    return ret 


def write_markdown(path, data):
    if path.is_dir():
        path = path / 'index.md'
    else:
        path = path.with_suffix('.md')
    for k in ('thumbnail', 'summary', 'title', 'user'):
        if k in data:
            if data[k]:
                data['meta'][k] = str(data.pop(k)).split('\n')
            elif k in data['meta']:
                del data['meta'][k]
    with open(path, 'w') as f:
        for k in data['meta']:
            v = data['meta'][k]
            print(f'{k}: {v[0]}', file=f)
            for vv in v[1:]:
                print(f'    {vv}', file=f)
        print('', file=f)
        print(data['description'], file=f)
