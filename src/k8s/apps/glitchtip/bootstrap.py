"""Configure Dex without a local password account or open registration."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "glitchtip.settings")

import django

django.setup()

from allauth.socialaccount.models import SocialApp
from django.db import transaction

from apps.organizations_ext.models import Organization, OrganizationSocialApp

with transaction.atomic():
    organization, _ = Organization.objects.get_or_create(
        slug="sgf-devs", defaults={"name": "SGF Devs"}
    )
    app, _ = SocialApp.objects.update_or_create(
        provider="openid_connect",
        provider_id="dex",
        defaults={
            "name": "Dex",
            "client_id": os.environ["OIDC_CLIENT_ID"],
            "secret": "",
            "settings": {
                "server_url": os.environ["OIDC_DISCOVERY_URL"],
                "oauth_pkce_enabled": True,
                "token_auth_method": "none",
            },
        },
    )
    OrganizationSocialApp.objects.update_or_create(
        social_app=app, defaults={"organization": organization, "is_public": True}
    )

print("Dex configured. The first authorized SSO user owns the SGF Devs organization.")
