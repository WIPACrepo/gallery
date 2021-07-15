"""Index images in ElasticSearch"""

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import os
import re
import shutil

from bs4 import BeautifulSoup
from elasticsearch import AsyncElasticsearch
from flask import Flask, request, render_template
from sigal.settings import read_settings
from sigal.utils import url_from_path

app = Flask(__name__, template_folder='theme/templates')

config = {
    'ES_ADDRESS': os.environ.get('ES_ADDRESS', 'localhost:9200'),
    'ES_INDEX': os.environ.get('ES_INDEX', 'gallery'),
    'SITE': os.environ.get('SITE', 'http://localhost:8000'),
    'BUILD_DIR': os.environ.get('BUILD_DIR', '_build'),
}

settings = read_settings('sigal.conf.py')


async def search(address, index_name, query, limit=100):
    es = AsyncElasticsearch(address)
    try:
        ret = await es.search(index=index_name, body={
            'query': {
                'combined_fields': {
                    'query': query,
                    'fields': ['title^3','keywords^10','summary^5','description^3','path','date^2','type'],
                    'operator': 'or',
                    'minimum_should_match': '3<66%',
                }
            },
            'size': limit
        })
        return {
            'total': ret['hits']['total']['value'],
            'results': ret['hits']['hits'],
        }
    finally:
        await es.close()


def get_pswp_hash(path):
    """Get a photoswipe hash for a media file"""
    if path.startswith('/'):
        path = path[1:]
    orig_name = Path(path).name
    album_html = (Path(config['BUILD_DIR']) / path).parent / 'index.html'
    with open(album_html) as f:
        soup = BeautifulSoup(f, 'html.parser')

    galleries = soup.find_all('div', 'gallery_pswp')
    for gid,gallery in enumerate(galleries):
        for pid,figure in enumerate(gallery.find_all('figure')):
            if figure.get('data-orig') == orig_name:
                return f'#&gid={gid+1}&pid={pid+1}'
    return ''


def process_results(results):
    ret = []
    for row in results:
        doc = row['_source']
        for key in ('title','keywords','summary','type'):
            if key not in doc:
                doc[key] = ''
        if not doc['path'].startswith('/'):
            doc['path'] = '/' + doc['path']
        doc['is_album'] = Path(doc['path']).suffix == ''
        if doc['is_album']:
            doc['thumbnail'] = Path(doc['path']) / 'thumbnails/thumb.jpg'
        else:
            p = Path(doc['path'])
            if p.suffix.lower() in settings['img_extensions']:
                doc['thumbnail'] = p.with_name('thumbnails') / p.name
            else:
                doc['thumbnail'] = p.with_name('thumbnails') / p.with_suffix('.jpg').name
        doc['thumbnail'] = config['SITE'] + str(doc['thumbnail'])
        if doc['is_album']:
            doc['url'] = config['SITE'] + doc['path']
        else:
            doc['url'] = config['SITE'] + str(Path(doc['path']).parent)
            if 'pswp_hash' in doc:
                hash = doc['pswp_hash']
            else:
                hash = get_pswp_hash(doc['path'])
                print('hash',hash)
            if hash:
                doc['url'] += hash
            doc['orig'] = config['SITE'] + doc['path']
        if 'date' not in doc and 'createdate' in doc:
            doc['date'] = datetime.fromtimestamp(doc['createdate']).strftime('%a %d %b %Y %I:%M:%S %p')
        ret.append(doc)
        print(doc)
    return ret


@app.route('/search', methods=['POST', 'GET'])
async def flask_search():
    query = ''
    try:
        if request.method == 'POST':
            query = request.form['query']
        else:
            query = request.args.get('query')
    except KeyError:
        pass

    limit = 100
    try:
        if request.method == 'POST':
            limit = int(request.form['limit'])
        else:
            limit = int(request.args.get('limit'))
    except (KeyError, TypeError, ValueError):
        pass

    if query:
        ret = await search(config['ES_ADDRESS'], config['ES_INDEX'], query, limit)
    else:
        ret = {'total': 0, 'results': []}


    ctx = {
        'album': {'title': 'Search'},
        'index_title': 'IceCube Gallery',
        'settings': settings,
        'theme': {'name': os.path.basename(settings['theme']),
                  'url': config['SITE']+'/static'},
        'query': query,
        'limit': limit,
        'total': ret['total'],
        'results': process_results(ret['results']),
    }
    if settings['user_css']:
        ctx['user_css'] = os.path.basename(settings['user_css'])

    return render_template('search.html', **ctx)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--address', default=config['ES_ADDRESS'], help='ElasticSearch address')
    parser.add_argument('-n', '--index-name', default=config['ES_INDEX'], help='ElasticSearch index name')
    parser.add_argument('--limit', default=100, type=int, help='Max number of results')
    parser.add_argument('query', nargs='+', help='query string')
    args = parser.parse_args()

    ret = await search(args.address, args.index_name, ' '.join(args.query), args.limit)

    print('total', ret['total'])
    for row in ret['results']:
        print(row)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
