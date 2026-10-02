\set ON_ERROR_STOP on

BEGIN;
SELECT pg_advisory_xact_lock(hashtext('glitchtip-dex-settings'));

-- Import on the client so secret JSON never appears in SQL statement text.
\lo_import /settings/settings.json
\set settings_oid :LASTOID
CREATE TEMP TABLE desired_settings ON COMMIT DROP AS
SELECT convert_from(lo_get(:settings_oid), 'UTF8')::jsonb AS settings;
SELECT lo_unlink(:settings_oid);

MERGE INTO organizations_ext_organization AS actual
USING jsonb_populate_record(NULL::organizations_ext_organization,
    (SELECT settings->'organization' FROM desired_settings)) AS desired
ON actual.slug = desired.slug
WHEN MATCHED AND actual.name IS DISTINCT FROM desired.name THEN
    UPDATE SET name = desired.name, modified = NOW()
WHEN NOT MATCHED THEN INSERT (
    name, slug, is_active, created, modified, is_accepting_events,
    open_membership, scrub_ip_addresses, event_throttle_rate,
    stripe_customer_id, is_deleted, metered_billing_enabled, overage_spend_cap_cents
) VALUES (desired.name, desired.slug, true, NOW(), NOW(), true, true, true, 0, '', false, false, 0);

MERGE INTO socialaccount_socialapp AS actual
USING jsonb_populate_record(NULL::socialaccount_socialapp,
    (SELECT settings->'social_app' FROM desired_settings)) AS desired
ON actual.provider = desired.provider AND actual.provider_id = desired.provider_id
WHEN MATCHED AND (actual.name, actual.client_id, actual.secret, actual.key, actual.settings)
    IS DISTINCT FROM (desired.name, desired.client_id, desired.secret, desired.key, desired.settings) THEN
    UPDATE SET name = desired.name, client_id = desired.client_id,
        secret = desired.secret, key = desired.key, settings = desired.settings
WHEN NOT MATCHED THEN INSERT (provider, provider_id, name, client_id, secret, key, settings)
    VALUES (desired.provider, desired.provider_id, desired.name, desired.client_id,
        desired.secret, desired.key, desired.settings);

INSERT INTO organizations_ext_organizationsocialapp AS actual (organization_id, social_app_id, is_public)
SELECT organization.id, app.id, (desired.settings->>'is_public')::boolean
FROM desired_settings AS desired
JOIN organizations_ext_organization AS organization
    ON organization.slug = desired.settings#>>'{organization,slug}'
JOIN socialaccount_socialapp AS app
    ON app.provider = desired.settings#>>'{social_app,provider}'
    AND app.provider_id = desired.settings#>>'{social_app,provider_id}'
ON CONFLICT (social_app_id) DO UPDATE
SET organization_id = EXCLUDED.organization_id, is_public = EXCLUDED.is_public
WHERE (actual.organization_id, actual.is_public) IS DISTINCT FROM (EXCLUDED.organization_id, EXCLUDED.is_public);

COMMIT;
