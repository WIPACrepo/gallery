"""
Credentials store and refresh.
"""
import asyncio
from datetime import datetime
import importlib
import logging
import os
from pathlib import Path
import random
import shutil
import time

from bs4 import BeautifulSoup
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_scan
from natsort import natsort_keygen, ns
from rest_tools.server import catch_error, RestServer, RestHandlerSetup, OpenIDLoginHandler, role_authorization
from tornado.template import Loader, Template
from tornado.web import HTTPError
from tornado.web import RequestHandler, StaticFileHandler
from wipac_dev_tools import from_environment
from sigal.settings import read_settings

import gallery
from ..index import Indexer
from ..util import SigalMixin, read_markdown, write_markdown


logger = logging.getLogger('server')


ROLES = {'read', 'upload', 'admin'}


class JinjaLoader(Loader):
    def _create_template(self, name: str) -> Template:
        path = os.path.join(self.root, name)
        with open(path, "r") as f:
            template_str = f.read()
        for before,after in [('endfor', 'end'), ('endif', 'end'), ('endblock', 'end'), ('-%}', '%}')]:
            template_str = template_str.replace(before, after)
        logging.debug('template %s = \n%s', name, template_str)
        template = Template(template_str, name=name, loader=self)
        return template


class SessionHandlerMixin:
    COOKIE_MAX_AGE = 31  # days

    """Store/load current user's session in cookies."""
    def get_current_user(self):
        """Get the current user, and set auth-related attributes."""
        try:
            raw_data = self.get_signed_cookie('user', max_age_days=SessionHandlerMixin.COOKIE_MAX_AGE)
            if not raw_data:
                return None
            username, name, role = raw_data.decode('utf-8').split('|')
            data = {
                'username': username,
                'name': name,
                'role': role,
            }
            self.auth_data = data
            return data['username']
        # Auth Failed
        except Exception:
            logger.debug('failed auth', exc_info=True)

        return None

    def store_tokens(
        self,
        access_token,
        access_token_exp,
        refresh_token=None,
        refresh_token_exp=None,
        user_info=None,
        user_info_exp=None,
    ):
        """Store jwt tokens and user info from OpenID-compliant auth source.

        Args:
            access_token (str): jwt access token
            access_token_exp (int): access token expiration in seconds
            refresh_token (str): jwt refresh token
            refresh_token_exp (int): refresh token expiration in seconds
            user_info (dict): user info (from id token or user info lookup)
            user_info_exp (int): user info expiration in seconds
        """
        username = user_info['preferred_username']
        name = user_info['name']
        role = 'read'
        try:
            if 'admin' in user_info['resource_access']['gallery']['roles']:
                role = 'admin'
            elif 'upload' in user_info['resource_access']['gallery']['roles']:
                role = 'upload'
        except KeyError:
            pass
        data = f'{username}|{name}|{role}'
        kwargs = {
            'expires_days': SessionHandlerMixin.COOKIE_MAX_AGE,
            'httponly': True,
            'secure': True,
            'samesite': 'Strict',
        }
        if full_url := getattr(self, 'full_url'):
            kwargs['domain'] = full_url.split('://',1)[-1].strip('/')
        self.set_signed_cookie('user', data, **kwargs)

    def clear_tokens(self):
        """Clear token data, usually on logout."""
        kwargs = {
            'httponly': True,
            'secure': True,
            'samesite': 'Strict',
        }
        if full_url := getattr(self, 'full_url'):
            kwargs['domain'] = full_url.split('://',1)[-1].strip('/')
        self.clear_cookie('user' **kwargs)


class BaseHandler(SigalMixin, SessionHandlerMixin, RequestHandler):
    def initialize(self, debug=False, full_url=None, sigal_settings=None, es=None, es_index=None, **kwargs):
        self.debug = debug
        self.auth_data = {}
        self.full_url = full_url
        self.sigal_settings = sigal_settings
        self.es = es
        self.es_index = es_index

    def get_template_namespace(self):
        data = super().get_template_namespace()
        data.update({
            'album': {
                'title': 'Editor',
                'author': self.sigal_settings['author'],
                'description': 'Gallery edit page',
                'url': '/edit',
                'index_url': '/',
                'breadcrumb': None,
            },
            'index_title': 'IceCube Gallery',
            'settings': self.sigal_settings,
            'search': {},
            'theme': {
                'name': os.path.basename(self.sigal_settings['theme']),
                'url': '/static',
            },
            'user_css': self.sigal_settings['user_css'],
        })
        if self.get_current_user:
            data['auth_data'] = self.auth_data
        return data

    def write_error(self, status_code, **kwargs):
        logging.info('error!')
        album = {
            'title': f'Error',
            'author': self.sigal_settings['author'],
            'breadcrumb': None,
            'description': 'Error loading page',
            'url': '/',
            'index_url': '/',
            'albums': [],
            'medias': [],
        }
        error = {
            'status_code': status_code,
            'reason': self._reason if self._reason else '',
        }
        self.render('error.html', album=album, error=error)

    def _get_thumb(self, path):
        basedir = Path(self.sigal_settings['source'])
        staticdir = Path(self.sigal_settings['destination'])
        web_path = staticdir / path.relative_to(basedir)
        if web_path.is_dir():
            ret = web_path / 'thumbnails' / 'thumb.jpg'
            if ret.exists():
                return '/'+str(ret.relative_to(staticdir))
            else:
                return '/static/echo/blank.gif'
        elif self._get_type(path) == 'image':
            ret = web_path.parent / 'thumbnails' / path.name
            if ret.exists():
                return '/'+str(ret.relative_to(staticdir))
            elif ret.with_suffix('.jpg').exists():
                return '/'+str(ret.relative_to(staticdir).with_suffix('.jpg'))
            else:
                return '/_src/'+str(path.relative_to(basedir))
        else:
            ret = web_path.parent / 'thumbnails' / path.name
            ret = ret.with_suffix('.jpg')
            if ret.exists():
                return '/'+str(ret.relative_to(staticdir))
            else:
                return '/static/echo/blank.gif'

    async def _add_to_es(self, path):
        logging.info('adding to ES: %s', path)
        try:
            i = Indexer(self.es, self.es_index, self.sigal_settings)
            await i.add_one(path)
        except Exception as e:
            logging.warning('failed to add to ES: %r', e)

    async def _remove_from_es(self, path):
        logging.info('deleting from ES: %s', path)
        try:
            i = Indexer(self.es, self.es_index, self.sigal_settings)
            await i.remove_one(path)
        except Exception as e:
            logging.warning('failed to delete from ES: %r', e)


class EditHandler(BaseHandler):
    """
    Handle album edit requests.
    """
    def _breadcrumbs(self, path):
        basedir = Path(self.sigal_settings['source'])
        if path == basedir:
            return []

        ret = []

        for p in path.parents:
            if p == basedir:
                break
            meta = read_markdown(p)
            logging.info('breadcrumb meta %s, %r', p, meta)
            if not meta['title']:
                meta['title'] = p.name
            ret.append((
                str(Path('/edit') / p.relative_to(basedir)),
                meta['title']
            ))
        ret.reverse()

        meta = read_markdown(path)
        if not meta['title']:
            meta['title'] = path.name
        ret.append((
            str(Path('/edit') / path.relative_to(basedir)),
            meta['title']
        ))

        return ret

    async def _get_album(self, album_path):
        basedir = Path(self.sigal_settings['source'])
        web_path = Path('/edit') / album_path.relative_to(basedir)

        meta = read_markdown(album_path)

        sorting = meta.get('meta', {}).get('sort', ['filename'])[0]
        if 'filename' in sorting:
            logging.info('sort by filename')
            sort_key = natsort_keygen(
                key=lambda s: s['name'], alg=ns.SIGNED|ns.LOCALE
            )
        elif 'meta.' in sorting:
            meta_key = sorting.split(".", 1)[1]
            logging.info('sort by meta %s', meta_key)
            sort_key = natsort_keygen(
                key=lambda s: s['meta'].get(meta_key, [""])[0], alg=ns.SIGNED|ns.LOCALE
            )
        else:
            sort_key = natsort_keygen(
                key=lambda s: s['name'], alg=ns.SIGNED|ns.LOCALE
            )
            logging.warning('unknown sorting: %r', sorting)

        reverse_sort = sorting[0] == '-'
        if reverse_sort:
            logging.info('REVERSED sorting')

        albums = []
        medias = []
        for child in album_path.iterdir():
            if child.suffix == '.md' or child.name == 'thumbnails':
                pass
            elif child.is_dir():
                data = {
                    'title': child.name,
                    'name': child.name,
                    'url': str(web_path / child.name),
                    'thumbnail': self._get_thumb(child),
                }
                data.update(read_markdown(child))
                if data['meta'].get('link', [''])[0]:
                    data['url'] = data['meta'].get('link', [''])[0]
                #logging.info('meta for %s = %r', child.name, data)
                if data['thumbnail'][0] != '/':
                    data['thumbnail'] = str(Path('/') / child.relative_to(basedir) / data['thumbnail'])
                albums.append(data)
            else:
                data = {
                    'type': self._get_type(child),
                    'name': child.name,
                    'url': str(web_path / child.name),
                    'thumbnail': self._get_thumb(child),
                    'title': '',
                    'description': '',
                    'summary': '',
                }
                data.update(read_markdown(child))
                #logging.info('meta for %s = %r', child.name, data)
                if data['thumbnail'][0] != '/':
                    data['thumbnail'] = str(Path('/') / child.relative_to(basedir) / data['thumbnail'])
                medias.append(data)

        albums.sort(key=sort_key, reverse=reverse_sort)
        medias.sort(key=sort_key, reverse=reverse_sort)

        album = {
            'title': f'Editor - {web_path.name}',
            'author': self.sigal_settings['author'],
            'breadcrumb': None,
            'breadcrumb_edit': self._breadcrumbs(album_path),
            'description': meta['description'],
            'url': str(web_path),
            'index_url': '/edit',
            'albums': albums,
            'medias': medias,
            'meta': meta,
        }
        self.render('album_edit.html', album=album)

    async def _update_album(self, album_path):
        if self.get_argument('delete', None) == 'delete':
            basedir = Path(self.sigal_settings['source'])
            web_path = Path('/edit') / album_path.relative_to(basedir)
            logging.info('deleting %s', media_path)
            shutil.rmtree(album_path)
            await self._remove_from_es(album_path)
            self.redirect(str(web_path.parent))
            return False
        else:
            meta = read_markdown(album_path)
            meta['title'] = self.get_argument('title')
            meta['summary'] = self.get_argument('summary')
            meta['description'] = self.get_argument('description')
            meta['meta']['sort'] = [self.get_argument('sort')]
            if self.get_argument('sort_reverse', 'false') == 'true':
                meta['meta']['sort'][0] = '-'+meta['meta']['sort'][0]
            write_markdown(album_path, meta)

            if meta['meta']['sort'][0].strip('-') == 'meta.orderweight':
                for k, v in self.request.body_arguments.items():
                    if k.startswith('orderweight-'):
                        filename = k.lstrip('orderweight-')
                        path = album_path / filename
                        meta = read_markdown(path)
                        meta['meta']['orderweight'] = [v[0].decode('utf-8')]
                        write_markdown(path, meta)

            await self._add_to_es(album_path)

    async def _get_media(self, media_path):
        basedir = Path(self.sigal_settings['source'])
        web_path = Path('/edit') / media_path.relative_to(basedir)

        media = {
            'type': self._get_type(media_path),
            'name': media_path.name,
            'url': str(web_path),
            'thumbnail': self._get_thumb(media_path),
            'src': str(Path('/') / media_path.relative_to(basedir)),
            'title': '',
            'description': '',
            'summary': '',
        }
        media.update(read_markdown(media_path))
        logging.info('meta for %s = %r', media_path.name, media)
        if media['thumbnail'][0] != '/':
            media['thumbnail'] = str(Path('/') / media_path.relative_to(basedir) / media['thumbnail'])

        album = {
            'title': f'Editor - {web_path.name}',
            'author': self.sigal_settings['author'],
            'breadcrumb': None,
            'breadcrumb_edit': self._breadcrumbs(media_path),
            'description': web_path.name,
            'url': str(web_path),
            'index_url': '/edit',
            'albums': [],
            'medias': [],
        }
        self.render('media_edit.html', album=album, media=media)

    async def _update_media(self, media_path):
        meta = read_markdown(media_path)
        if self.get_argument('delete', None) == 'delete':
            basedir = Path(self.sigal_settings['source'])
            web_path = Path('/edit') / media_path.relative_to(basedir)
            logging.info('deleting %s', media_path)
            media_path.unlink()
            md_path = media_path.with_suffix('.md')
            if md_path.exists():
                md_path.unlink()
            if meta.get('thumbnail', None):
                thumb_path = media_path.parent / meta['thumbnail']
                if thumb_path.exists():
                    thumb_path.unlink()
            await self._remove_from_es(media_path)
            self.redirect(str(web_path.parent))
            return False
        else:
            meta['title'] = self.get_argument('title')
            meta['summary'] = self.get_argument('summary')
            meta['description'] = self.get_argument('description')
            write_markdown(media_path, meta)
            await self._add_to_es(media_path)

    #@role_authorization(roles=['admin', 'upload'])
    async def get(self, path):
        #role = self.auth_data['role']

        basedir = Path(self.sigal_settings['source'])
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

    #@role_authorization(roles=['admin'])
    async def post(self, path):

        basedir = Path(self.sigal_settings['source'])
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
    async def post(self):
        web_redirect = self.get_argument('album', '/edit')
        web_path = Path(web_redirect)

        basedir = Path(self.sigal_settings['source'])
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
                meta = read_markdown(new_album_path)
                meta['title'] = newdir
                if self.current_user:
                    meta['user'] = self.current_user
                meta['meta']['createdate'][0] = time.time()
                if thumbnail:
                    thumb_dir = new_album_path / 'thumbnails'
                    thumb_dir.mkdir()
                    thumb_path = thumb_dir / thumbnail.filename
                    thumb_path = thumb_path.with_stem('thumb')
                    meta['thumbnail'] =  'thumbnails/' + thumb_path.name
                write_markdown(new_album_path, meta)
            await self._add_to_es(new_album_path)
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

                    meta = read_markdown(media_path)
                    meta['title'] = item['filename']
                    if self.current_user:
                        meta['user'] = self.current_user
                    meta['meta']['createdate'] = [time.time()]
                    write_markdown(media_path, meta)
                    await self._add_to_es(media_path)

                    files.append(item['filename'])
            logging.info("Files: %d %r", len(files), files)

        self.redirect(str(web_redirect))



class SearchHandler(BaseHandler):
    """
    Handle searches
    """
    def _process_results(self, results):
        basedir = Path(self.sigal_settings['source'])
        ret = []
        for row in results:
            doc = row['_source']

            media_path = basedir / doc['path'].strip('/')

            for key in ('title','keywords','summary','type'):
                if key not in doc:
                    doc[key] = ''
            if not doc['path'].startswith('/'):
                doc['path'] = '/' + doc['path']

            doc['is_album'] = media_path.is_dir()
            doc['thumbnail'] = self._get_thumb(media_path)

            md = read_markdown(media_path)
            for key in ('title', 'keywords', 'summary', 'description'):
                if val := md.get(key):
                    doc[key] = val

            if thumb := md.get('thumbnail'):
                if thumb[0] != '/':
                    if media_path.is_dir():
                        thumb = str(Path('/') / media_path.relative_to(basedir) / thumb)
                    else:
                        thumb = str(Path('/') / media_path.relative_to(basedir).parent / thumb)
                doc['thumbnail'] = thumb

            if doc['is_album']:
                doc['url'] = doc['path'] + '/'
            else:
                doc['url'] = str(Path(doc['path']).parent) + '/'
                if 'pswp_hash' in doc:
                    hash = doc['pswp_hash']
                else:
                    hash = self._get_pswp_hash(doc['path'])
                if hash:
                    doc['url'] += hash
                doc['orig'] = doc['path']
            if 'date' not in doc and 'createdate' in doc:
                doc['date'] = datetime.fromtimestamp(doc['createdate']).strftime('%a %d %b %Y %I:%M:%S %p')
            ret.append(doc)
            print(doc)
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
            ret = await self.es.search(index=self.es_index, body={
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
            #logging.info('ret: %r', ret)
            total = ret['hits']['total']['value']
            results = self._process_results(ret['hits']['hits'])
        else:
            total = 0
            results = []

        album = {
            'title': 'Search',
            'author': self.sigal_settings['author'],
            'breadcrumb': None,
            'description': 'Gallery search page',
            'url': '/search',
            'index_url': '/',
            'albums': [],
            'medias': [],
        }
        self.render('search.html', album=album, query=query, limit=limit, total=total, results=results)

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
            ret = await self.es.search(index=self.es_index, body={
                'query': {
                    'combined_fields': {
                        'query': 'icecube logo',
                        'fields': ['title^3','keywords^10','summary^5','description^3','path','date^2','type'],
                        'operator': 'or',
                        'minimum_should_match': '3<66%',
                    }
                },
                'size': 1
            })
            status['es'] = 'ok'
        except Exception:
            logger.info('error from ES', exc_info=True)
            status['es'] = 'fail'
            self.send_error(500, reason='error from elasticsearch')

        self.write(status)


class Login(SessionHandlerMixin, OpenIDLoginHandler):
    def initialize(self, full_url=None, **kwargs):
        super().initialize(**kwargs)
        self.full_url = full_url


class Logout(BaseHandler):
    @catch_error
    async def get(self):
        self.clear_tokens()
        self.current_user = None
        self.redirect('/')


class Server:
    def __init__(self):
        default_config = {
            'HOST': 'localhost',
            'PORT': 8080,
            'DEBUG': False,
            'SIGAL_SETTINGS': 'sigal.conf.py',
            'OPENID_URL': '',
            'OPENID_AUDIENCE': 'gallery',
            'WEB_URL': 'https://gallery.icecube.wisc.edu',
            'OAUTH2_CLIENT_ID': 'gallery',
            'OAUTH2_CLIENT_SECRET': '',
            'ES_ADDRESS': 'http://localhost:9200',
            'ES_INDEX': 'gallery',
            'COOKIE_SECRET': '',
            'CI_TESTING': '',
        }
        config = from_environment(default_config)

        # get package data
        template_path = str(importlib.resources.files('gallery')/'data'/'theme'/'templates')
        if template_path is None or not os.path.exists(template_path):
            logger.info('template path: %r',template_path)
            raise Exception('bad template path')
        logging.info('template path: %s', template_path)

        settings_path = config['SIGAL_SETTINGS']
        if (not settings_path) or not os.path.exists(settings_path):
            logger.info('settings path: %r',settings_path)
            raise Exception('bad sigal settings path')
        logging.info('sigal settings: %s', settings_path)
        sigal_settings = read_settings(settings_path)

        static_path = Path(sigal_settings['destination'])
        if not static_path.is_dir():
            logger.info('static path: %r',static_path)
            raise Exception('bad static path')
        static_path = str(static_path)
        logging.info('static path: %s', static_path)

        static_src_path = Path(sigal_settings['source'])
        if not static_src_path.is_dir():
            logger.info('static src path: %r',static_src_path)
            raise Exception('bad static src path')
        static_src_path = str(static_src_path)
        logging.info('static (src) path: %s', static_src_path)

        rest_config = {
            'debug': config['DEBUG'],
            'server_header': 'Gallery/' + gallery.__version__,
        }
        if config['OPENID_URL']:
            logging.info(f'enabling auth via {config["OPENID_URL"]} for aud "{config["OPENID_AUDIENCE"]}"')
            rest_config.update({
                'auth': {
                    'openid_url': config['OPENID_URL'],
                    'audience': config['OPENID_AUDIENCE'],
                }
            })
        elif config['CI_TESTING']:
            rest_config.update({
                'auth': {
                    'secret': 'secret',
                }
            })
        else:
            raise RuntimeError('OPENID_URL not specified, and CI_TESTING not enabled!')

        handler_args = RestHandlerSetup(rest_config)
        full_url = config['WEB_URL']
        handler_args['full_url'] = full_url
        login_handler_args = handler_args.copy()
        if config['OAUTH2_CLIENT_ID'] and config['OAUTH2_CLIENT_SECRET']:
            logging.info('enabling website login"')
            login_handler_args['oauth_client_id'] = config['OAUTH2_CLIENT_ID']
            login_handler_args['oauth_client_secret'] = config['OAUTH2_CLIENT_SECRET']
            login_handler_args['oauth_client_scope'] = 'profile'
        elif config['CI_TESTING']:
            logger.info('CI_TESTING: no login for testing')
        else:
            raise RuntimeError('OAUTH2_CLIENT_ID or OAUTH2_CLIENT_SECRET not specified, and CI_TESTING not enabled!')

        handler_args['sigal_settings'] = sigal_settings

        self.es = AsyncElasticsearch(hosts=config['ES_ADDRESS'])
        handler_args['es'] = self.es
        handler_args['es_index'] = config['ES_INDEX']

        if config['COOKIE_SECRET']:
            cookie_secret = config['COOKIE_SECRET']
            log_cookie_secret = cookie_secret[:4] + 'X'*(len(cookie_secret)-8) + cookie_secret[-4:]
            logger.info('using supplied cookie secret %r', log_cookie_secret)
        else:
            cookie_secret = ''.join(hex(random.randint(0,15))[-1] for _ in range(64))

        server = RestServer(
            debug=config['DEBUG'],
            serve_traceback=False,
            cookie_secret=cookie_secret,
            xsrf_cookie_kwargs={
                'httponly': True,
                'secure': True,
                'samesite': 'Strict',
                'domain': full_url.split('://')[-1].strip('/'),
            },
            login_url=full_url+'/edit/login',
            template_path=template_path,
            template_loader=JinjaLoader(template_path, autoescape="xhtml_escape"),
            max_body_size=2**31,  # support 2GB uploads
        )

        server.add_route('/edit/login', Login, login_handler_args)
        server.add_route('/edit/logout', Logout, handler_args)
        server.add_route('/edit/_upload', UploadHandler, handler_args)
        server.add_route(r'/edit(?P<path>.*)', EditHandler, handler_args)
        server.add_route('/search', SearchHandler, handler_args)
        server.add_route('/healthz', HealthHandler, handler_args)
        if config['CI_TESTING']:
            server.add_route(r'/_src/(.*)', StaticFileHandler, {"path": static_src_path}),
            server.add_route(r'/(.*)', StaticFileHandler, {"path": static_path}),

        server.startup(address=config['HOST'], port=config['PORT'])

        self.server = server

    async def start(self):
        return
        if not self.refresh_service_task:
            self.refresh_service_task = asyncio.create_task(self.refresh_service.run())

    async def stop(self):
        await self.server.stop()
        self.es.close()
        return
        if self.refresh_service_task:
            self.refresh_service_task.cancel()
            try:
                await self.refresh_service_task
            except asyncio.CancelledError:
                pass  # ignore cancellations
            finally:
                self.refresh_service_task = None
