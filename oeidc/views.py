from __future__ import annotations

import jwt
import logging

from django.http import HttpRequest
from rest_framework.response import Response

from sentry.auth.services.auth.model import RpcAuthProvider
from sentry.auth.view import AuthView
from sentry.utils import json
from sentry.organizations.services.organization.model import RpcOrganization
from sentry.plugins.base.response import DeferredResponse
from sentry.utils.signing import urlsafe_b64decode

from .constants import ERR_INVALID_RESPONSE, ISSUER, REQUIRED_CLAIM

logger = logging.getLogger("sentry.auth.oeidc")


class FetchUser(AuthView):
    def __init__(self, domains, version, *args, **kwargs):
        self.domains = domains
        self.version = version
        super().__init__(*args, **kwargs)

    def has_role(self, data, role):
        return any(
            role in details.get("roles", [])
            for details in data.get("resource_access", {}).values()
        )

    def dispatch(self, request: HttpRequest, helper) -> Response:  # type: ignore
        data = helper.fetch_state("data")

        try:
            if REQUIRED_CLAIM and not self.has_role(
                jwt.decode(data["access_token"], options={"verify_signature": False}),
                REQUIRED_CLAIM,
            ):
                logger.error("Required claim %s not available" % REQUIRED_CLAIM)
                return helper.error(ERR_INVALID_RESPONSE)
        except Exception as e:
            logger.exception(e)
            logger.error(
                "Error reading and decoding access_token from OAuth response: %s" % data
            )
            return helper.error(ERR_INVALID_RESPONSE)

        try:
            id_token = data["id_token"]
        except KeyError:
            logger.error("Missing id_token in OAuth response: %s" % data)
            return helper.error(ERR_INVALID_RESPONSE)

        try:
            _, payload, _ = map(urlsafe_b64decode, id_token.split(".", 2))
        except Exception as exc:
            logger.error("Unable to decode id_token: %s" % exc, exc_info=True)
            return helper.error(ERR_INVALID_RESPONSE)

        try:
            payload = json.loads(payload)
        except Exception as exc:
            logger.error("Unable to decode id_token payload: %s" % exc, exc_info=True)
            return helper.error(ERR_INVALID_RESPONSE)

        if not payload.get("email"):
            logger.error("Missing email in id_token payload: %s" % id_token)
            return helper.error(ERR_INVALID_RESPONSE)

        # support legacy style domains with pure domain regexp
        if self.version is None:
            domain = extract_domain(payload["email"])
        else:
            domain = payload.get("hd")

        helper.bind_state("domain", domain)
        helper.bind_state("user", payload)

        return helper.next_step()


def oeidc_configure_view(
    request: HttpRequest, organization: RpcOrganization, auth_provider: RpcAuthProvider
) -> DeferredResponse:
    config = auth_provider.config
    if config.get("domain"):
        domains: list[str] | None
        domains = [config["domain"]]
    else:
        domains = config.get("domains")
    return DeferredResponse(
        "oeidc/configure.html", {"provider_name": ISSUER or "", "domains": domains or []}
    )


def extract_domain(email):
    return email.rsplit("@", 1)[-1]
