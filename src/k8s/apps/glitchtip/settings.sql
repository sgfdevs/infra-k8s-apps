\set ON_ERROR_STOP on
\getenv client_id OIDC_CLIENT_ID
\getenv discovery_url OIDC_DISCOVERY_URL

BEGIN;

-- Both application replicas configure the same provider.
SELECT pg_advisory_xact_lock(hashtext('glitchtip-dex-settings'));

-- Import on the client so the secret never appears in SQL statement text.
\lo_import /settings/client-secret
\set secret_oid :LASTOID

CREATE TEMP TABLE desired_social_app ON COMMIT DROP AS
SELECT :'client_id'::text AS client_id,
       convert_from(lo_get(:secret_oid), 'UTF8') AS secret,
       jsonb_build_object(
           'server_url', :'discovery_url',
           'oauth_pkce_enabled', true,
           'token_auth_method', 'client_secret_post'
       ) AS settings;

SELECT lo_unlink(:secret_oid);

INSERT INTO organizations_ext_organization (
    name, slug, is_active, created, modified, is_accepting_events,
    open_membership, scrub_ip_addresses, event_throttle_rate,
    stripe_customer_id, is_deleted, metered_billing_enabled,
    overage_spend_cap_cents
)
VALUES (
    'SGF Devs', 'sgf-devs', true, NOW(), NOW(), true,
    true, true, 0, '', false, false, 0
)
ON CONFLICT (slug) DO NOTHING;

UPDATE socialaccount_socialapp AS app
SET name = 'Dex', client_id = desired.client_id,
    secret = desired.secret, settings = desired.settings
FROM desired_social_app AS desired
WHERE app.provider = 'openid_connect' AND app.provider_id = 'dex';

INSERT INTO socialaccount_socialapp (
    provider, provider_id, name, client_id, secret, key, settings
)
SELECT 'openid_connect', 'dex', 'Dex', client_id, secret, '', settings
FROM desired_social_app
WHERE NOT EXISTS (
    SELECT 1 FROM socialaccount_socialapp
    WHERE provider = 'openid_connect' AND provider_id = 'dex'
);

INSERT INTO organizations_ext_organizationsocialapp (
    organization_id, social_app_id, is_public
)
SELECT organization.id, app.id, true
FROM organizations_ext_organization AS organization
JOIN socialaccount_socialapp AS app
    ON app.provider = 'openid_connect' AND app.provider_id = 'dex'
WHERE organization.slug = 'sgf-devs'
ON CONFLICT (social_app_id) DO UPDATE
SET organization_id = EXCLUDED.organization_id, is_public = EXCLUDED.is_public;

COMMIT;
