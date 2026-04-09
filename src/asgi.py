"""
ASGI config for src project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

default_settings = (
    'src.settings.prod'
    if os.getenv('DJANGO_ENV', 'development').lower() == 'production'
    else 'src.settings.dev'
)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', default_settings)

application = get_asgi_application()
