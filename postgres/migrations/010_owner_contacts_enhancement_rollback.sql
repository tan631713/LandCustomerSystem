BEGIN;

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS address TEXT;

UPDATE contacts
SET address = registered_address
WHERE BTRIM(COALESCE(address, '')) = ''
  AND BTRIM(COALESCE(registered_address, '')) <> '';

DROP INDEX IF EXISTS idx_owner_contact_relations_deactivated_by;
DROP INDEX IF EXISTS idx_contacts_home_phone_normalized;
DROP INDEX IF EXISTS idx_contacts_mobile_phone_normalized;
DROP INDEX IF EXISTS idx_contacts_contact_address;
DROP INDEX IF EXISTS idx_contacts_registered_address;

ALTER TABLE owner_contact_relations DROP COLUMN IF EXISTS deactivated_by;
ALTER TABLE owner_contact_relations DROP COLUMN IF EXISTS deactivated_at;
ALTER TABLE owner_contact_relations ALTER COLUMN notes TYPE TEXT;

ALTER TABLE contacts DROP COLUMN IF EXISTS identity_note;
ALTER TABLE contacts DROP COLUMN IF EXISTS work_address;
ALTER TABLE contacts DROP COLUMN IF EXISTS contact_address;
ALTER TABLE contacts DROP COLUMN IF EXISTS registered_address;
ALTER TABLE contacts ALTER COLUMN notes TYPE TEXT;

DELETE FROM schema_migrations WHERE version = 10;

COMMIT;
