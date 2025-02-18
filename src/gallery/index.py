"""Index images in ElasticSearch"""

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import logging
from pathlib import Path
import re
from typing import Any, cast


from elasticsearch import AsyncElasticsearch, BadRequestError
from elasticsearch.client import IndicesClient
from elasticsearch.helpers import async_streaming_bulk

from .config import ENV, config_logging
from .util import read_metadata, get_type, now


def hash(s):
    return re.sub(r'[ \;\"\*\+\/\\\|\?\#\>\<]','', s).lower()



class Indexer:
    def __init__(self, es, es_index):
        self.es = es
        self.es_index = es_index
        self.index_name = es_index

    @asynccontextmanager
    async def swap_index(self):
        ic = cast(Any, IndicesClient(client=self.es))
        index_name = f'{self.es_index}-{now().strftime("%Y%m%dt%H%M%S")}'

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

    def index_metadata(self, path: Path, meta: dict | None = None) -> dict[str, Any]:
        root_path = ENV.SOURCE
        doc_path = str(path.relative_to(root_path))
        doc = {
            '_index': self.index_name,
            '_id': hashlib.sha1(doc_path.encode('utf8')).hexdigest(),
            'path': doc_path,
        }

        if not meta:
            meta = read_metadata(path)
        for key in ('title', 'summary', 'keywords', 'description', 'user'):
            if value := meta.get(key, '').strip():
                doc[key] = str(value)

        if createdate := meta.get('createdate', ''):
            try:
                doc['date'] = datetime.fromtimestamp(float(createdate)).strftime('%A %d %B %Y %I:%M:%S %p')
            except TypeError:
                logging.error("bad createdate: %r", createdate)
                raise

        if path.is_dir():
            doc['type'] = 'Album'
        else:
            type_ = get_type(path)
            if type_ == 'image':
                doc['type'] = 'Image'
            elif type_ == 'video':
                doc['type'] = 'Video'
            else:
                doc['type'] = 'Other Media'

        logging.debug('indexing %r', doc)
        return doc

    async def generate_files(self, root_path: Path):
        for root,dirs,files in root_path.walk(top_down=True):
            for f in list(dirs):
                if f == 'thumbnails':
                    dirs.remove(f)
                    continue
                path = root / f
                logging.info('processing %s', path)
                doc = self.index_metadata(path)
                yield doc
            for f in files:
                if f.endswith('.meta.json'):
                    continue
                path = root / f
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

    async def add_one(self, path: Path, meta: dict | None = None):
        """Add a single document"""
        docs = [
            self.index_metadata(path, meta=meta)
        ]
        async for ok, result in async_streaming_bulk(client=self.es, actions=docs, chunk_size=1000, max_retries=2, yield_ok=False, request_timeout=60):
            action, result = result.popitem()
            if not ok:
                logging.warning('failed to process: %r', result)
                raise RuntimeError('failed to process')

    async def remove_one(self, path):
        """Remove a single document"""
        root_path = ENV.SOURCE
        doc_path = str(path.relative_to(root_path))
        id_ = hashlib.sha1(doc_path.encode('utf8')).hexdigest()
        await self.es.delete(self.index_name, id_, timeout=60)

    async def search(self, query, limit=100):
        return await self.es.search(index=self.es_index, body={
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


async def main():
    config_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ENV.SOURCE, help="album root")
    parser.add_argument('-a', '--address', default=ENV.ES_ADDRESS, help='ElasticSearch address')
    parser.add_argument('-n', '--index-name', default=ENV.ES_INDEX, help='ElasticSearch index name')
    parser.add_argument('--chunk-size', default=ENV.ES_CHUNK_SIZE, type=int, help='ElasticSearch upload chunk size')
    args = parser.parse_args()

    es = AsyncElasticsearch(hosts=args.address)
    es_indexer = Indexer(es, args.index_name)

    try:
        async with es_indexer.swap_index():
            await es_indexer.stream(args.root)
    finally:
        await es.close()


if __name__ == '__main__':
    asyncio.run(main())
