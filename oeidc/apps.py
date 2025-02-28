from django.apps import AppConfig


class Config(AppConfig):
    name = "oeidc"

    def ready(self):
        from sentry import auth

        from .provider import OEIDCProvider

        auth.register(OEIDCProvider)
