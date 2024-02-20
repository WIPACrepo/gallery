"""Index images in ElasticSearch"""

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import logging
from pathlib import Path
import os
import re
import shutil


from elasticsearch import AsyncElasticsearch, BadRequestError
from elasticsearch.client import IndicesClient
from elasticsearch.helpers import async_streaming_bulk
from sigal.settings import read_settings
from wipac_dev_tools import from_environment

from .util import SigalMixin, read_markdown


def hash(s):
    return re.sub('[ \;\"\*\+\/\\\|\?\#\>\<]','', s).lower()



class Indexer(SigalMixin):
    def __init__(self, es, es_index, sigal_settings):
        self.es = es
        self.es_index = es_index
        self.index_name = es_index
        self.sigal_settings = sigal_settings

    @asynccontextmanager
    async def swap_index(self):
        ic = IndicesClient(client=self.es)
        index_name = f'{self.es_index}-{datetime.utcnow().strftime("%Y%m%dt%H%M%S")}'

        # create index
        try:
            await ic.create(index=index_name, body={
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
        except BadRequestError as e:
            if e.error != 'resource_already_exists_exception':
                raise

        try:
            self.index_name = index_name
            yield
        finally:
            self.index_name = self.es_index

            # swap alias
            if await ic.exists_alias(name=self.es_index):
                await ic.delete_alias(index='_all', name=self.es_index)
            await ic.put_alias(index=index_name, name=self.es_index)

            # clean up old indexes
            ret = await ic.get(index='_all')
            for index in ret:
                if index not in (self.es_index, index_name):
                    await ic.delete(index=index)

    def index_metadata(self, path):
        root_path = self.sigal_settings['source']
        doc_path = str(path.relative_to(root_path))
        doc = {
            '_index': self.index_name,
            '_id': hashlib.sha1(doc_path.encode('utf8')).hexdigest(),
            'path': doc_path,
        }

        meta = read_markdown(path)

        for key in ('title', 'summary', 'keywords', 'description', 'user'):
            if value := meta.get(key, '').strip():
                doc[key] = str(value)

        if createdate := meta['meta'].get('createdate', [''])[0]:
            doc['date'] = datetime.fromtimestamp(float(createdate)).strftime('%A %d %B %Y %I:%M:%S %p')

        if path.is_dir():
            doc['type'] = 'Album'
        else:
            type_ = self._get_type(path)
            if type_ == 'image':
                doc['type'] = 'Image'
                doc['pswp_hash']: self._get_pswp_hash(doc_path)
            elif type_ == 'video':
                doc['type'] = 'Video'
                doc['pswp_hash']: self._get_pswp_hash(doc_path)
            else:
                doc['type'] = 'Other Media'

        logging.debug('indexing %r', doc)
        return doc

    async def generate_files(self, root_path):
        for root,dirs,files in os.walk(root_path, topdown=True):
            for f in list(dirs):
                if f == 'thumbnails':
                    dirs.remove(f)
                    continue
                path = Path(root).absolute() / f
                logging.info('processing %s', path)
                doc = self.index_metadata(path)
                yield doc
            for f in files:
                if f.endswith('.md'):
                    continue
                path = Path(root).absolute() / f
                logging.info('processing %s', path)
                doc = self.index_metadata(path)
                yield doc

    async def stream(self, root_path, chunk_size=1000):
        """Recursively add documents"""
        async for ok, result in async_streaming_bulk(client=self.es, actions=self.generate_files(root_path), chunk_size=chunk_size, max_retries=2, yield_ok=False, request_timeout=60):
            action, result = result.popitem()
            if not ok:
                logging.warning('failed to process: %r', result)
                raise RuntimeError('failed to process')
                
    async def add_one(self, path):
        """Add a single document"""
        docs = [
            self.index_metadata(path)
        ]
        async for ok, result in async_streaming_bulk(client=self.es, actions=docs, chunk_size=1000, max_retries=2, yield_ok=False, request_timeout=60):
            action, result = result.popitem()
            if not ok:
                logging.warning('failed to process: %r', result)
                raise RuntimeError('failed to process')

    async def remove_one(self, path):
        """Remove a single document"""
        root = self.sigal_settings['source']
        doc_path = str(path.relative_to(root_path))
        id_ = hashlib.sha1(doc_path.encode('utf8')).hexdigest()
        await self.es.delete(self.index_name, id_, timeout=60)


async def main():
    default_config = {
        'SIGAL_SETTINGS': 'sigal.conf.py',
        'ES_ADDRESS': 'http://localhost:9200',
        'ES_INDEX': 'gallery',
        'ES_CHUNK_SIZE': 1000,
    }
    config = from_environment(default_config)
    logging.basicConfig(level=logging.INFO)

    settings_path = config['SIGAL_SETTINGS']
    if (not settings_path) or not os.path.exists(settings_path):
        logger.info('settings path: %r',settings_path)
        raise Exception('bad sigal settings path')
    logging.info('sigal settings: %s', settings_path)
    sigal_settings = read_settings(settings_path)

    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path, help="album root")
    parser.add_argument('-a', '--address', default=config['ES_ADDRESS'], help='ElasticSearch address')
    parser.add_argument('-n', '--index-name', default=config['ES_INDEX'], help='ElasticSearch index name')
    parser.add_argument('--chunk-size', default=config['ES_CHUNK_SIZE'], type=int, help='ElasticSearch upload chunk size')
    args = parser.parse_args()

    es = AsyncElasticsearch(hosts=args.address)
    es_indexer = Indexer(es, args.index_name, sigal_settings)
    
    try:
        async with es_indexer.swap_index():
            await es_indexer.stream(args.root)
    finally:
        await es.close()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
