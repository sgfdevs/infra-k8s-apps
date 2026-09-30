\set ON_ERROR_STOP on
\getenv desired LISTMONK_SETTINGS

BEGIN;

-- COPY keeps generated SMTP credentials out of SQL statement text.
CREATE TEMP TABLE smtp_credentials (
    username text,
    password text,
    host text,
    port text,
    from_address text,
    configuration_set text
) ON COMMIT DROP;

\copy smtp_credentials FROM PROGRAM 'printf "%s\t%s\t%s\t%s\t%s\t%s\n" "$SMTP_USERNAME" "$SMTP_PASSWORD" "$SMTP_HOST" "$SMTP_PORT" "$SMTP_FROM_ADDRESS" "$SMTP_CONFIGURATION_SET"'

CREATE TEMP TABLE desired_settings ON COMMIT DROP AS
SELECT key, value
FROM jsonb_each(:'desired'::jsonb || jsonb_build_object(
    'app.from_email', (SELECT from_address FROM smtp_credentials)
));

UPDATE desired_settings
SET value = jsonb_build_array((value -> 0) || jsonb_build_object(
    'host', c.host,
    'port', c.port::integer,
    'username', c.username,
    'password', c.password,
    'email_headers', jsonb_build_array(jsonb_build_object(
        'X-SES-CONFIGURATION-SET', c.configuration_set
    ))
))
FROM smtp_credentials AS c
WHERE key = 'smtp';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM smtp_credentials
        WHERE username = '' OR password = '' OR host = ''
            OR from_address = '' OR configuration_set = ''
    ) THEN
        RAISE EXCEPTION 'Incomplete SMTP configuration';
    END IF;

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
