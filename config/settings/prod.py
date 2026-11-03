from decouple import config

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = config("SECRET_KEY")  # engin sjálfgefin gildi í prod

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
