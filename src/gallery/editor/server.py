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

from rest_tools.server import catch_error, RestServer, RestHandlerSetup, RestHandler, OpenIDLoginHandler, role_authorization
from tornado.template import Loader, Template
from tornado.web import HTTPError
from tornado.web import RequestHandler as TornadoRequestHandler
from wipac_dev_tools import from_environment
from sigal.settings import read_settings

import gallery


logger = logging.getLogger('server')


ROLES = {'read', 'upload', 'admin'}


class JinjaLoader(Loader):
    def _create_template(self, name: str) -> Template:
        path = os.path.join(self.root, name)
        with open(path, "rb") as f:
            template_str = f.read()
        for before,after in [('endfor', 'end'), ('endif', 'end'), ('endblock', 'end'), ('-%}', '%}')]:
            template_str.replace(before, after)
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
            return data['u']
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


class BaseHandler(SessionHandlerMixin, RestHandler):
    def initialize(self, full_url=None, sigal_settings=None, **kwargs):
        self.full_url = full_url
        self.sigal_settings = sigal_settings
        super().initialize(**kwargs)

    def get_template_namespace(self):
        data = super().get_template_namespace()
        data.update({
            'album': {'title': 'Editor', 'description': 'Gallery edit page', 'url': '/edit', 'index_url': '/', 'breadcrumb': None},
            'index_title': 'IceCube Gallery',
            'settings': self.sigal_settings,
            'theme': {
                'name': os.path.basename(self.sigal_settings['theme']),
                'url': self.full_url+'/static',
            },
        })
        if self.get_current_user:
            data['auth_data'] = self.auth_data
        return data



class EditHandler(BaseHandler):
    """
    Handle album edit requests.
    """
    async def _get_album(self, album_path):
        basedir = Path(self.sigal_settings['source'])
        web_path = album_path.relative_to(basedir)
        
        children = {}
        for child in album_path.iterdir():
            children[child.name] = child

        album = {
            'title': f'Editor - {web_path.name}',
            'breadcrumb': [('/edit', 'Edit')],
            'description': web_path.name,
            'url': os.path.join('/edit', web_path),
            'index_url': '/', 
        }
        self.render('album_edit.html', album=album)

    async def _get_media(self, media_path):
        basedir = Path(self.sigal_settings['source'])
        web_path = media_path.relative_to(basedir)

        album = {
            'title': f'Editor - {web_path.name}',
            'breadcrumb': [('/edit', 'Edit')],
            'description': web_path.name,
            'url': os.path.join('/edit', web_path),
            'index_url': '/', 
        }
        self.render('album_edit.html', album=album)


    @role_authorization(roles=['admin', 'upload'])
    async def get(self, path):
        role = self.auth_data['role']

        basedir = Path(self.sigal_settings['source'])
        if not basedir.exists():
            raise HTTPError(500, reason='album source does not exist')

        media_path = basedir / path.strip('/')
        if not media_path.exists():
            raise HTTPError(500, reason='album source does not exist')
        elif media_path.is_dir():
            await self._get_album(media_path)
        else:
            await self._get_media(media_path)


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
            pass
        except Exception:
            logger.info('error from refresh service', exc_info=True)
            self.send_error(500, reason='error from refresh service')
            return

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


class Error(TornadoRequestHandler):
    def prepare(self):
        self.set_status(404)
        self.render('404.html')


class Server:
    def __init__(self):
        default_config = {
            'HOST': 'localhost',
            'PORT': 8080,
            'DEBUG': False,
            'SIGAL_SETTINGS': '',
            'OPENID_URL': 'https://keycloak.icecube.wisc.edu/auth/realms/IceCube',
            'OPENID_AUDIENCE': 'gallery',
            'WEB_URL': 'https://gallery.icecube.wisc.edu',
            'OAUTH2_CLIENT_ID': 'gallery',
            'OAUTH2_CLIENT_SECRET': '',
            'COOKIE_SECRET': '',
            'CI_TESTING': '',
        }
        config = from_environment(default_config)

        # get package data
        static_path = str(importlib.resources.files('gallery')/'data'/'theme'/'static')
        if static_path is None or not os.path.exists(static_path):
            logger.info('static path: %r',static_path)
            raise Exception('bad static path')
        template_path = str(importlib.resources.files('gallery')/'data'/'theme'/'templates')
        if template_path is None or not os.path.exists(template_path):
            logger.info('template path: %r',template_path)
            raise Exception('bad template path')

        settings_path = config['SIGAL_SETTINGS']
        if (not settings_path) or not os.path.exists(settings_path):
            logger.info('settings path: %r',settings_path)
            raise Exception('bad sigal settings path')
        sigal_settings = read_settings(settings_path)

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

        if config['COOKIE_SECRET']:
            cookie_secret = config['COOKIE_SECRET']
            log_cookie_secret = cookie_secret[:4] + 'X'*(len(cookie_secret)-8) + cookie_secret[-4:]
            logger.info('using supplied cookie secret %r', log_cookie_secret)
        else:
            cookie_secret = ''.join(hex(random.randint(0,15))[-1] for _ in range(64))

        server = RestServer(
            debug=config['DEBUG'],
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
            static_path=static_path,
            max_body_size=2**31,  # support 2GB uploads
        )

        server.add_route('/edit/login', Login, login_handler_args)
        server.add_route('/edit/logout', Logout, handler_args)
        #server.add_route(r'/edit/(?P<path>.*)/_upload', UploadHandler, handler_args)
        server.add_route(r'/edit/(?P<path>.*)', EditHandler, handler_args)
        #server.add_route('/search', SearchHandler, handler_args)
        server.add_route('/healthz', HealthHandler, handler_args)
        # the static gallery is not served here, and will 404

        server.startup(address=config['HOST'], port=config['PORT'])

        self.server = server

    async def start(self):
        for collection in self.indexes:
            existing = await self.db[collection].index_information()
            for name in self.indexes[collection]:
                if name not in existing:
                    logging.info('DB: creating index %s:%s', collection, name)
                    kwargs = self.indexes[collection][name]
                    await self.db[collection].create_index(name=name, **kwargs)

        if not self.refresh_service_task:
            self.refresh_service_task = asyncio.create_task(self.refresh_service.run())

    async def stop(self):
        await self.server.stop()
        if self.refresh_service_task:
            self.refresh_service_task.cancel()
            try:
                await self.refresh_service_task
            except asyncio.CancelledError:
                pass  # ignore cancellations
            finally:
                self.refresh_service_task = None
