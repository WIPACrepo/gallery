"""
Credentials store and refresh.
"""
import asyncio
from datetime import datetime
import logging
from pathlib import Path
import shutil
import time
from typing import Any

from elasticsearch import AsyncElasticsearch
from rest_tools.server import catch_error, RestServer, RestHandlerSetup, KeycloakUsernameMixin
from tornado.web import HTTPError
from tornado.web import RequestHandler, StaticFileHandler

import gallery
from .albums import Album, AlbumItem, Media
from .config import ENV
from .index import Indexer
from .caching import RedisInstance
from .util import read_metadata, write_metadata, get_type


logger = logging.getLogger('server')


ROLES = {'read', 'upload', 'admin'}


class BaseHandler(KeycloakUsernameMixin, RequestHandler):
    def initialize(self, debug, indexer, auth, **kwargs):
        self.debug = debug
        self.auth = auth
        self.auth_data = {}
        self.indexer = indexer
        self.page_cache = RedisInstance()

    def set_default_headers(self):
        self._headers['Server'] = 'Gallery/' + gallery.__version__

    def get_current_user(self):
        """Get the current user, and set auth-related attributes."""
        try:
            type, token = self.request.headers['Authorization'].split(' ', 1)
            if type.lower() != 'bearer':
                raise Exception('bad header type')
            logging.debug('token: %r', token)
            data = self.auth.validate(token)
            self.auth_data = data
            return data['sub']
        # Auth Failed
        except Exception as e:
            if self.debug and 'Authorization' in self.request.headers:
                logging.debug('Authorization: %r', self.request.headers['Authorization'])
            logging.debug('failed auth', exc_info=True)

        return None

    def get_template_namespace(self):
        data = super().get_template_namespace()
        data.update({
            'album': None,
            'media': None,
            'breadcrumbs': None,
            'title': 'Gallery',
            'search': {},
            'auth_data': self.auth_data,
            'template_url': '/static',
        })
        logging.info("namespace: %r", data)
        return data

    def write_error(self, status_code, **kwargs):
        logging.info('error!')
        error = {
            'status_code': status_code,
            'reason': self._reason if self._reason else '',
        }
        self.render('error.html', error=error)

    async def _add_to_es(self, path: Path, meta: dict | None = None):
        logging.info('adding to ES: %s', path)
        try:
            await self.indexer.add_one(path=path, meta=meta)
        except Exception as e:
            logging.warning('failed to add to ES: %r', e)

    async def _remove_from_es(self, path: Path):
        logging.info('deleting from ES: %s', path)
        try:
            await self.indexer.remove_one(path)
        except Exception as e:
            logging.warning('failed to delete from ES: %r', e)

    def _breadcrumbs(self, path, prefix=None):
        basedir = ENV.SOURCE
        if path == basedir:
            return []
        if not prefix:
            prefix = Path('/')

        ret = []

        for p in path.parents:
            if p == basedir:
                break
            meta = read_metadata(p)
            logging.info('breadcrumb meta %s, %r', p, meta)
            if not meta['title']:
                meta['title'] = p.name
            ret.append((
                str(prefix / p.relative_to(basedir)),
                meta['title']
            ))
        ret.reverse()

        meta = read_metadata(path)
        if not meta['title']:
            meta['title'] = path.name
        ret.append((
            str(prefix / path.relative_to(basedir)),
            meta['title']
        ))

        return ret


class AlbumHandler(BaseHandler):
    async def get(self, path):
        try:
            ret = await self.page_cache.get(str(path))
        except KeyError:
            pass
        except Exception:
            logging.info('bad cache get', exc_info=True)
        else:
            if ret['version'] != gallery.__version__:
                await self.page_cache.delete(str(path))
            else:
                self.write(ret['body'])
                return

        basedir = Path(ENV.SOURCE)
        if not basedir.exists():
            logging.warning('album basedir %s does not exist', basedir)
            raise HTTPError(500, reason=f'album source does not exist')

        media_path = basedir / path.strip('/')
        if not media_path.exists():
            logging.warning('album path %s does not exist', media_path)
            raise HTTPError(500, reason=f'album path does not exist')
        elif media_path.is_dir():
            album = Album(media_path)
            title = f'Gallery - {media_path.name}'
            body = self.render_string('album.html', title=title, album=album, breadcrumbs=self._breadcrumbs(media_path))
        else:
            self.redirect('/_src'+path)
            return

        try:
            await self.page_cache.set(str(path), {
                'version': gallery.__version__,
                'body': body.decode('utf-8'),
            })
        except Exception:
            logging.info('cannot cache page', exc_info=True)

        self.write(body)


class EditHandler(BaseHandler):
    """
    Handle album edit requests.
    """

    async def _get_album(self, album_path):
        album = Album(album_path, prefix=Path('/edit'))
        title = f'Editor - {album_path.name}'
        self.render('album_edit.html', title=title, album=album, breadcrumbs=self._breadcrumbs(album_path, prefix=Path('/edit')))

    async def _update_album(self, album_path):
        if self.get_argument('delete', None) == 'delete':
            basedir = Path(ENV.SOURCE)
            web_path = Path('/edit') / album_path.relative_to(basedir)
            logging.info('deleting %s', album_path)
            shutil.rmtree(album_path)
            await self._remove_from_es(album_path)
            self.redirect(str(web_path.parent))
            return False
        else:
            meta = read_metadata(album_path)
            meta['title'] = self.get_argument('title')
            meta['summary'] = self.get_argument('summary')
            meta['description'] = self.get_argument('description')
            meta['sort'] = self.get_argument('sort')
            if self.get_argument('sort_reverse', 'false') == 'true':
                meta['sort'] = '-' + meta['sort']
            write_metadata(album_path, meta)

            if meta['sort'][0].strip('-') == 'meta.orderweight':
                for k, v in self.request.body_arguments.items():
                    if k.startswith('orderweight-'):
                        filename = k.lstrip('orderweight-')
                        path = album_path / filename
                        meta2 = read_metadata(path)
                        meta2['orderweight'] = v[0].decode('utf-8')
                        write_metadata(path, meta2)

            await self._add_to_es(album_path, meta=meta)

        try:
            await self.page_cache.delete(str(album_path))
        except Exception:
            pass

    async def _get_media(self, media_path):
        media = Media(media_path, prefix=Path('/edit'))
        title = f'Editor - {media.name}'
        self.render('media_edit.html', title=title, media=media, breadcrumbs=self._breadcrumbs(media_path, prefix=Path('/edit')))

    async def _update_media(self, media_path):
        meta = read_metadata(media_path)
        if self.get_argument('delete', None) == 'delete':
            basedir = Path(ENV.SOURCE)
            web_path = Path('/edit') / media_path.relative_to(basedir)
            logging.info('deleting %s', media_path)
            media_path.unlink()
            meta_path = media_path.with_suffix('.meta.json')
            if meta_path.exists():
                meta_path.unlink()
            if t := meta.get('thumbnail', None):
                thumb_path = media_path.parent / t
                if thumb_path.exists():
                    thumb_path.unlink()
            await self._remove_from_es(media_path)
            self.redirect(str(web_path.parent))
            return False
        else:
            meta['title'] = self.get_argument('title')
            meta['summary'] = self.get_argument('summary')
            meta['description'] = self.get_argument('description')
            write_metadata(media_path, meta)
            await self._add_to_es(media_path, meta=meta)

        try:
            await self.page_cache.delete(str(media_path.parent))
        except Exception:
            pass

    @catch_error
    async def get(self, path):
        basedir = Path(ENV.SOURCE)
        if not basedir.exists():
            logging.warning('album basedir %s does not exist', basedir)
            raise HTTPError(500, reason=f'album source does not exist')

        media_path = basedir / path.strip('/')
        if not media_path.exists():
            logging.warning('album path %s does not exist', media_path)
            raise HTTPError(500, reason=f'album path does not exist')
        elif media_path.is_dir():
            await self._get_album(media_path)
        else:
            await self._get_media(media_path)

    @catch_error
    async def post(self, path):
        basedir = ENV.SOURCE
        if not basedir.exists():
            logging.warning('album basedir %s does not exist', basedir)
            raise HTTPError(500, reason=f'album source does not exist')

        media_path = basedir / path.strip('/')
        if not media_path.exists():
            logging.warning('album path %s does not exist', media_path)
            raise HTTPError(500, reason=f'album path does not exist')
        elif media_path.is_dir():
            if (await self._update_album(media_path)) is not False:
                await self._get_album(media_path)
        else:
            if (await self._update_media(media_path)) is not False:
                await self._get_media(media_path)

def sanitize_name(name):
    return ''.join(x for x in name.replace(' ', '-') if (x.isalnum() or x in '-_.'))

class UploadHandler(BaseHandler):
    """
    Handle file uploads
    """
    @catch_error
    async def post(self):
        web_redirect = self.get_argument('album', '/edit')
        web_path = Path(web_redirect)

        basedir = ENV.SOURCE
        if not basedir.exists():
            logging.warning('album basedir %s does not exist', basedir)
            raise HTTPError(500, reason=f'album source does not exist')

        album_path = basedir / web_path.relative_to('/edit')
        logging.info('album_path: %s', album_path)

        if newdir := self.get_argument('newdir', None):
            logging.info("New Subalbum!")
            logging.info("name: %s", newdir)
            thumbnail = None
            for fieldname, items in self.request.files.items():
                for item in items:
                    thumbnail = item['filename']
            logging.info("thumbnail: %r", thumbnail)

            new_album_path = album_path / sanitize_name(newdir)
            if not new_album_path.exists():
                new_album_path.mkdir()
                meta = read_metadata(new_album_path)
                meta['title'] = newdir
                if self.current_user:
                    meta['user'] = self.current_user
                meta['createdate'] = time.time()
                if thumbnail:
                    thumb_dir = new_album_path / 'thumbnails'
                    thumb_dir.mkdir()
                    thumb_path = thumb_dir / thumbnail.filename
                    thumb_path = thumb_path.with_stem('thumb')
                    meta['thumbnail'] =  'thumbnails/' + thumb_path.name
                write_metadata(new_album_path, meta)
            await self._add_to_es(new_album_path, meta=meta)
        else:
            logging.info("Upload!")
            logging.info("Args: %r", self.request.body_arguments)
            files = []
            for fieldname, items in self.request.files.items():
                for item in items:
                    name = sanitize_name(item['filename'])
                    media_path = album_path / name
                    with open(media_path, 'wb') as f:
                        f.write(item['body'])

                    meta = read_metadata(media_path)
                    meta['title'] = item['filename']
                    if self.current_user:
                        meta['user'] = self.current_user
                    meta['createdate'] = time.time()
                    write_metadata(media_path, meta)
                    await self._add_to_es(media_path, meta=meta)

                    files.append(item['filename'])
            logging.info("Files: %d %r", len(files), files)

        self.redirect(str(web_redirect))


class SearchHandler(BaseHandler):
    """
    Handle searches
    """
    def _get_pswp_hash(self, url_path, existing_album=None):
        """Get a photoswipe hash for a media file"""
        logging.info('getting pswp hash')
        if existing_album:
            images = existing_album.images
            videos = existing_album.videos
        else:
            if url_path.startswith('/'):
                url_path = url_path[1:]
            orig_name = Path(url_path).name
            basedir = Path(ENV.SOURCE)
            if not url_path:
                album_path = basedir
            else:
                album_path = (basedir / url_path).parent
            images = []
            videos = []
            for path in album_path.iterdir():
                if path.is_file():
                    type_ = get_type(path)
                    if type_ == 'image':
                        images.append(path)
                    elif type_ == 'video':
                        videos.append(path)

        gid = 0
        for pid, media in enumerate(images):
            if media.name == orig_name:
                logging.info('pswp hash %d.%d', gid+1, pid+1)
                return f'#&gid={gid+1}&pid={pid+1}'
        gid = 1
        for pid, media in enumerate(videos):
            if media.name == orig_name:
                logging.info('pswp hash %d.%d', gid+1, pid+1)
                return f'#&gid={gid+1}&pid={pid+1}'

        return ''

    def _process_results(self, results):
        basedir = ENV.SOURCE
        ret = []
        for row in results:
            doc = row['_source']
            media_path = basedir / doc['path'].lstrip('/')
            logging.info('processing search result %s', media_path)

            if media_path.is_dir():
                media = AlbumItem(media_path)
            else:
                media = Media(media_path)
                if media.type in ('image', 'video'):
                    if hash := self._get_pswp_hash(doc['path']):
                        media.url = media.album_url + hash

            ret.append(media)
        return ret

    @catch_error
    async def get(self):
        query = self.get_argument('query', '')
        try:
            limit = int(self.get_argument('limit', '100'))
        except (TypeError, ValueError):
            limit = 100

        logging.info('limit: %d, query: %s', limit, query)
        if query:
            ret = await self.indexer.search(query, limit)
            #logging.info('ret: %r', ret)
            total = ret['hits']['total']['value']
            results = self._process_results(ret['hits']['hits'])
        else:
            total = 0
            results = []

        title = 'Gallery - Search'
        self.render('search.html', title=title, query=query, limit=limit, total=total, results=results)

    async def post(self):
        await self.get()


class HealthHandler(BaseHandler):
    """
    Handle health requests.
    """
    async def get(self):
        """
        Get health status.

        Returns based on exit code, 200 = ok, 500 = failure
        """
        status = {
            'now': datetime.utcnow().isoformat(),
        }
        try:
            await self.indexer.search('icecube logo', limit=1)
            status['es'] = 'ok'
        except Exception:
            logger.info('error from ES', exc_info=True)
            status['es'] = 'fail'
            self.send_error(500, reason='error from elasticsearch')

        self.write(status)


class StaticServer(StaticFileHandler):
    def set_default_headers(self):
        self._headers['Server'] = 'Gallery/' + gallery.__version__


class Server:
    def __init__(self):
        template_path = ENV.THEME / 'templates'
        logging.info('template path: %s', template_path)
        if not template_path.is_dir():
            raise Exception('bad template path')
        
        static_path = ENV.THEME / 'static'
        logging.info('static path: %s', static_path)
        if not static_path.is_dir():
            raise Exception('bad static path')

        source_path = ENV.SOURCE
        logging.info('src path: %s', source_path)
        if not source_path.is_dir():
            raise Exception('bad src path')

        rest_config: dict[str, Any] = {
            'debug': ENV.CI_TEST,
        }
        if not ENV.CI_TEST:
            rest_config['auth'] = {
                'openid_url': ENV.OPENID_URL,
                'audience': ENV.OPENID_AUDIENCE,
            }

        handler_args = RestHandlerSetup(rest_config)
        self.es = AsyncElasticsearch(hosts=ENV.ES_ADDRESS)
        handler_args['indexer'] = Indexer(self.es, ENV.ES_INDEX)

        server = RestServer(
            debug=ENV.CI_TEST,
            serve_traceback=False,
            template_path=str(template_path),
            max_body_size=2**31,  # support 2GB uploads
        )

        server.add_route('/edit/_upload', UploadHandler, handler_args)
        server.add_route(r'/edit(?P<path>.*)', EditHandler, handler_args)
        server.add_route('/search', SearchHandler, handler_args)
        server.add_route('/healthz', HealthHandler, handler_args)
        server.add_route(r'/_src/(.*)', StaticServer, {"path": str(source_path)})
        server.add_route(r'/static/(.*)', StaticServer, {"path": str(static_path)})
        server.add_route('/(favicon.ico)', StaticServer, {"path": str(static_path)})
        server.add_route(r'/(?P<path>.*)', AlbumHandler, handler_args)

        server.startup(address=ENV.SERVER_HOST, port=ENV.SERVER_PORT)

        self.server = server

    async def start(self):
        return
        if not self.refresh_service_task:
            self.refresh_service_task = asyncio.create_task(self.refresh_service.run())

    async def stop(self):
        await self.server.stop()
        await self.es.close()
        return
        if self.refresh_service_task:
            self.refresh_service_task.cancel()
            try:
                await self.refresh_service_task
            except asyncio.CancelledError:
                pass  # ignore cancellations
            finally:
                self.refresh_service_task = None
