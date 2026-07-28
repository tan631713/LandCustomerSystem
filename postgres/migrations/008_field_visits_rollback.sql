-- Manual rollback for PostgreSQL schema version 8.
--
-- Run only when version 8 must be removed before field-visit data becomes
-- authoritative.  Take a complete PostgreSQL and attachment backup first.
-- The normal application startup never runs this file automatically.

BEGIN;

DELETE FROM schema_migrations WHERE version = 8;

ALTER TABLE attachments
DROP COLUMN IF EXISTS field_visit_route_item_id;

ALTER TABLE attachments
DROP COLUMN IF EXISTS contact_log_id;

ALTER TABLE contact_logs
DROP COLUMN IF EXISTS field_visit_route_item_id;

ALTER TABLE contact_logs
DROP COLUMN IF EXISTS longitude;

ALTER TABLE contact_logs
DROP COLUMN IF EXISTS latitude;

ALTER TABLE contact_logs
DROP COLUMN IF EXISTS contacted_at;

DROP TABLE IF EXISTS field_visit_idempotency_keys;
DROP TABLE IF EXISTS field_visit_status_history;
DROP TABLE IF EXISTS field_visit_route_items;
DROP TABLE IF EXISTS field_visit_routes;

ALTER TABLE ownership_locations
DROP COLUMN IF EXISTS address_fingerprint;

ALTER TABLE ownership_locations
DROP COLUMN IF EXISTS geocode_error;

ALTER TABLE ownership_locations
DROP COLUMN IF EXISTS geocoded_at;

ALTER TABLE ownership_locations
DROP COLUMN IF EXISTS geocode_source;

ALTER TABLE ownership_locations
DROP COLUMN IF EXISTS geocode_status;

COMMIT;
