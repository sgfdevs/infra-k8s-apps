\set ON_ERROR_STOP on

BEGIN;

-- Import on the client so secret JSON never appears in SQL statement text.
-- Remove the imported large object within the same transaction.
\lo_import /settings/settings.json
\set settings_oid :LASTOID

CREATE TEMP TABLE desired_settings ON COMMIT DROP AS
SELECT key, value
FROM jsonb_each(convert_from(lo_get(:settings_oid), 'UTF8')::jsonb);

SELECT lo_unlink(:settings_oid);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM desired_settings AS d
        LEFT JOIN settings AS s USING (key)
        WHERE s.key IS NULL
    ) THEN
        RAISE EXCEPTION 'Unknown managed Listmonk setting';
    END IF;
END;
$$;

UPDATE settings AS s
SET value = d.value, updated_at = NOW()
FROM desired_settings AS d
WHERE s.key = d.key AND s.value IS DISTINCT FROM d.value;

COMMIT;
