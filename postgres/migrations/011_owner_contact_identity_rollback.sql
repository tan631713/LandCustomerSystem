BEGIN;

ALTER TABLE contacts
DROP COLUMN IF EXISTS external_id;

DELETE FROM schema_migrations WHERE version = 11;

COMMIT;
