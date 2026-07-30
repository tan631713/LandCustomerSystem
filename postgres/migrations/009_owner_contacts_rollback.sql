BEGIN;

DROP INDEX IF EXISTS uq_owner_contact_primary_active;
DROP INDEX IF EXISTS uq_owner_contact_relations_active;
DROP INDEX IF EXISTS idx_owner_contact_relations_sort;
DROP INDEX IF EXISTS idx_owner_contact_relations_owner_active;
DROP INDEX IF EXISTS idx_owner_contact_relations_contact;
DROP INDEX IF EXISTS idx_owner_contact_relations_owner;
DROP TABLE IF EXISTS owner_contact_relations;

DROP INDEX IF EXISTS idx_contacts_is_active;
DROP INDEX IF EXISTS idx_contacts_home_phone;
DROP INDEX IF EXISTS idx_contacts_mobile_phone;
DROP INDEX IF EXISTS idx_contacts_name;
DROP TABLE IF EXISTS contacts;

DELETE FROM schema_migrations WHERE version = 9;

COMMIT;
