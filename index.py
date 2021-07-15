"""Index images in ElasticSearch"""

import argparse
import asyncio
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import os
import re
import shutil


from bs4 import BeautifulSoup
from elasticsearch import AsyncElasticsearch
from elasticsearch.client import IndicesClient
from elasticsearch.helpers import async_streaming_bulk
from sigal.settings import read_settings


config = {
    'ES_ADDRESS': os.environ.get('ES_ADDRESS', 'localhost:9200'),
    'ES_INDEX': os.environ.get('ES_INDEX', 'gallery'),
    'BUILD_DIR': os.environ.get('BUILD_DIR', '_build'),
}

settings = read_settings('sigal.conf.py')


def hash(s):
    return re.sub('[ \;\"\*\+\/\\\|\?\#\>\<]','', s).lower()


@lru_cache(maxsize=4)
def get_html(path):
    with open(path) as f:
        return BeautifulSoup(f, 'html.parser')


def get_pswp_hash(path):
    """Get a photoswipe hash for a media file"""
    if path.startswith('/'):
        path = path[1:]
    orig_name = Path(path).name
    album_html = (Path(config['BUILD_DIR']) / path).parent / 'index.html'
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


def index(doc, index_path):
    description = ''
    with index_path.open() as f:
        blank = False
        for line in f:
            line = line.strip('\n')
            if ':' in line:
                name, value = [x.strip() for x in line.split(':',1)]
                if name and value:
                    if name.lower() in ('title','keywords','summary'):
                        doc[name.lower()] = value
                    elif name.lower() in ('createdate','moddate'):
                        doc[name.lower()] = float(value)
            elif not line:
                blank = True
                continue
            if blank:
                description += ' '+line

    description = description.strip()
    if description:
        doc['description'] = description

    if 'createdate' in doc:
        doc['date'] = datetime.fromtimestamp(doc['createdate']).strftime('%A %d %B %Y %I:%M:%S %p')

    p = Path(doc['path'])
    if p.suffix == '':
        doc['type'] = 'Album'
    elif p.suffix.lower() in settings['img_extensions']:
        doc['type'] = 'Image'
    elif p.suffix.lower() in settings['video_extensions']:
        doc['type'] = 'Video'
    else:
        doc['type'] = 'Other Media'

    return doc

async def generate_files(index_name, args):
    for root,dirs,files in os.walk(args.root):
        for f in dirs:
            path = Path(root) / f
            print('processing', path)
            doc = {
                '_index': index_name,
                'path': str(path.relative_to(args.root)),
            }
            if (path / 'index.md').exists():
                doc = index(doc, index_path=(path / 'index.md'))
            yield doc
        for f in files:
            path = Path(root) / f
            if f.endswith('.md'):
                continue
            print('processing', path)
            doc_path = str(path.relative_to(args.root))
            doc = {
                '_index': index_name,
                'path': doc_path,
                'pswp_hash': get_pswp_hash(doc_path),
            }
            if path.with_suffix('.md').exists():
                doc = index(doc, index_path=path.with_suffix('.md'))
            yield doc


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path, help="album root")
    parser.add_argument('-a', '--address', default=config['ES_ADDRESS'], help='ElasticSearch address')
    parser.add_argument('-n', '--index-name', default=config['ES_INDEX'], help='ElasticSearch index name')
    args = parser.parse_args()

    index_name = f'{args.index_name}-{datetime.utcnow().strftime("%Y%m%dt%H%M%S")}'

    es = AsyncElasticsearch(args.address)
    ic = IndicesClient(es)
    try:
        # create index
        await ic.create(index_name, body={
            'mappings': {
                'properties': {
                    'path': {'type': 'text'},
                    'title': {'type': 'text'},
                    'keywords': {'type': 'text'},
                    'summary': {'type': 'text'},
                    'description': {'type': 'text'},
                    'createdate': {'type': 'date', 'format': 'strict_date_optional_time||epoch_second'},
                    'moddate': {'type': 'date', 'format': 'strict_date_optional_time||epoch_second'},
                    'date': {'type': 'text'},
                    'type': {'type': 'text'},
                }
            }
        })

        # add documents
        async for ok, result in async_streaming_bulk(es, generate_files(index_name, args), chunk_size=5000, max_retries=2, yield_ok=False, request_timeout=60):
            action, result = result.popitem()
            if not ok:
                print('failed to process', result)

        # swap alias
        if await ic.exists_alias(args.index_name):
            await ic.delete_alias('_all', args.index_name)
        await ic.put_alias(index_name, args.index_name)

        # clean up old indexes
        ret = await ic.get('_all')
        for index in ret:
            if index != index_name:
                await ic.delete(index)
    finally:
        await es.close()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
