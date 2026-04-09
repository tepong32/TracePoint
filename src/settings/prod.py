from django.core.exceptions import ImproperlyConfigured

from .base import *


DEBUG = False
ALLOWED_HOSTS = get_env_list('DJANGO_ALLOWED_HOSTS')

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        'DJANGO_ALLOWED_HOSTS must be set when using src.settings.prod.'
    )
