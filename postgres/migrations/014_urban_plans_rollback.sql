-- Rollback for schema version 14 (urban plans). Take a backup first.
-- Lands keep all of their other data; only the plan grouping is removed.

DROP INDEX IF EXISTS lands_urban_plan_idx;
ALTER TABLE lands DROP COLUMN IF EXISTS urban_plan_id;
DROP TABLE IF EXISTS urban_plans;
DELETE FROM schema_migrations WHERE version = 14;
