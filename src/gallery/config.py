import dataclasses as dc
import logging
from pathlib import Path

from wipac_dev_tools import from_environment_as_dataclass

@dc.dataclass(frozen=True)
class EnvConfig:
    SOURCE: Path = Path('albums')
    THEME: Path = Path('src/gallery/data/theme')

    IMG_EXTENSIONS: list = dc.field(default_factory=lambda: ['jpg', 'jpeg', 'png', 'gif'])
    VIDEO_EXTENSIONS: list = dc.field(default_factory=lambda: ['avi', 'mp4', 'webm', 'ogv', '3gp'])

    SERVER_HOST: str = 'localhost'
    SERVER_PORT: int = 8080

    REDIS_HOST: str = 'localhost'
    REDIS_PORT: int = 6379

    ES_ADDRESS: str = 'http://localhost:9200'
    ES_INDEX: str = 'gallery'
    ES_CHUNK_SIZE: int = 1000

    OPENID_URL: str = 'https://keycloak.icecube.wisc.edu/auth/realms/IceCube'
    OPENID_AUDIENCE: str = ''

    CI_TEST: bool = False
    LOG_LEVEL: str = 'INFO'

    def __post_init__(self) -> None:
        object.__setattr__(self, 'LOG_LEVEL', self.LOG_LEVEL.upper())  # b/c frozen

ENV = from_environment_as_dataclass(EnvConfig, collection_sep=',')


def config_logging():
    # handle logging
    setlevel = {
        'CRITICAL': logging.CRITICAL,  # execution cannot continue
        'FATAL': logging.CRITICAL,
        'ERROR': logging.ERROR,  # something is wrong, but try to continue
        'WARNING': logging.WARNING,  # non-ideal behavior, important event
        'WARN': logging.WARNING,
        'INFO': logging.INFO,  # initial debug information
        'DEBUG': logging.DEBUG  # the things no one wants to see
    }

    if ENV.LOG_LEVEL not in setlevel:
        raise Exception('LOG_LEVEL is not a proper log level')
    logformat = '%(asctime)s %(levelname)s %(name)s %(module)s:%(lineno)s - %(message)s'
    logging.basicConfig(format=logformat, level=setlevel[ENV.LOG_LEVEL])
