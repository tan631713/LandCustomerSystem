"""PostgreSQL customer-record persistence workflows."""

import json
from pathlib import Path

from customer_api.data_source_base import _decrypt_record, _encrypted_record, _filter_records, _row_dict
from customer_api.field_visit_service import (
    location_address_fingerprint,
    normalize_location_address,
)
from customer_api.postgres_schema import (
    IDENTITY_PRIMARY_KEY_CONSTRAINTS,
    repair_postgres_identity_sequences,
)
from customer_api.postgres_urban_plans import (
    apply_record_urban_plan,
    assign_imported_lands,
)
from customer_postgres_keys import land_key_for, owner_key_for
from customer_security import decrypt_value, make_fernet


class PostgreSQLRecordMixin:
    @staticmethod
    def _record_address_before_update(conn, user, record_id):
        row = conn.execute(
            """
            SELECT COALESCE(ownership.address_override, owner.address) AS address
            FROM ownerships ownership
            JOIN owners owner ON owner.id = ownership.owner_id
            WHERE ownership.id = %s
            """,
            (int(record_id),),
        ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return decrypt_value(make_fernet(user.data_key), row.get("address"))

    @staticmethod
    def _synchronize_location_address(
        conn, record_id, previous_address, current_address
    ):
        fingerprint = location_address_fingerprint(current_address)
        if normalize_location_address(previous_address) != normalize_location_address(
            current_address
        ):
            conn.execute(
                """
                UPDATE ownership_locations SET
                    geocode_status = 'pending',
                    geocode_source = NULL,
                    geocoded_at = NULL,
                    geocode_error = NULL,
                    address_fingerprint = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE ownership_id = %s
                """,
                (fingerprint, int(record_id)),
            )
            return
        conn.execute(
            """
            UPDATE ownership_locations
            SET address_fingerprint = COALESCE(address_fingerprint, %s)
            WHERE ownership_id = %s
            """,
            (fingerprint, int(record_id)),
        )

    def _record_write_with_identity_repair(self, operation):
        """Retry one rolled-back write after repairing a stale id sequence."""

        try:
            with self._connect() as conn:
                return operation(conn)
        except self._psycopg.errors.UniqueViolation as exc:
            diagnostic = getattr(exc, "diag", None)
            constraint_name = str(
                getattr(diagnostic, "constraint_name", "") or ""
            )
            if constraint_name not in IDENTITY_PRIMARY_KEY_CONSTRAINTS:
                raise
        with self._connect() as repair_conn:
            repair_postgres_identity_sequences(repair_conn)
        with self._connect() as retry_conn:
            return operation(retry_conn)

    def list_records(
        self,
        user,
        *,
        query="",
        filters=None,
        offset=0,
        limit=100,
    ):
        with self._connect() as conn:
            rows = conn.execute(self.RECORD_SELECT + " ORDER BY ownership.id DESC").fetchall()
        records = [_decrypt_record(row, user) for row in rows]
        matched = _filter_records(records, query=query, filters=filters)
        offset = max(0, int(offset))
        limit = max(1, int(limit))
        return {"total": len(matched), "items": matched[offset : offset + limit]}

    def get_record(self, user, record_id):
        with self._connect() as conn:
            row = conn.execute(
                self.RECORD_SELECT + " WHERE ownership.id = %s",
                (int(record_id),),
            ).fetchone()
        return None if row is None else _decrypt_record(row, user)

    def _save_owner_and_land(self, conn, user, values):
        encrypted = _encrypted_record(user, values)
        owner_row = conn.execute(
            """
            INSERT INTO owners (owner_key, owner_name, external_id, address, birth_year)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (owner_key) DO UPDATE SET
                owner_name = EXCLUDED.owner_name,
                external_id = EXCLUDED.external_id,
                address = EXCLUDED.address,
                birth_year = EXCLUDED.birth_year,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                owner_key_for(values, user.data_key),
                encrypted["owner_name"],
                encrypted.get("external_id"),
                encrypted.get("address"),
                encrypted.get("birth_year"),
            ),
        ).fetchone()
        land_row = self._save_land(conn, values)
        return int(owner_row["id"]), int(land_row["id"]), encrypted

    @staticmethod
    def _save_land(conn, values):
        """Resolve an existing parcel by both canonical key and visible fields.

        Older migrations can contain a valid district/section/land-number row
        whose stored ``land_key`` was generated by an earlier normalization
        rule.  An INSERT that only targets ``land_key`` then collides with the
        separate visible-field UNIQUE constraint and returns an opaque API 500.
        Resolve both identities before writing so editing such a row is safe.
        """

        district = values.get("district") or ""
        section = values.get("section") or ""
        subsection = values.get("subsection") or ""
        land_number = values.get("land_number") or ""
        land_key = land_key_for(values)
        row = conn.execute(
            """
            SELECT id
            FROM lands
            WHERE (district = %s AND section = %s AND land_number = %s)
               OR land_key = %s
            ORDER BY
                CASE
                    WHEN district = %s AND section = %s AND land_number = %s
                    THEN 0 ELSE 1
                END,
                id
            LIMIT 1
            """,
            (
                district,
                section,
                land_number,
                land_key,
                district,
                section,
                land_number,
            ),
        ).fetchone()
        if row is None:
            return conn.execute(
                """
                INSERT INTO lands (
                    land_key, district, section, subsection, land_number, area,
                    declared_value
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    land_key,
                    district,
                    section,
                    subsection,
                    land_number,
                    values.get("area"),
                    values.get("declared_value"),
                ),
            ).fetchone()

        land_id = int(row["id"])
        return conn.execute(
            """
            UPDATE lands SET
                land_key = CASE
                    WHEN NOT EXISTS (
                        SELECT 1 FROM lands other
                        WHERE other.land_key = %s AND other.id <> %s
                    ) THEN %s
                    ELSE land_key
                END,
                district = %s,
                section = %s,
                subsection = %s,
                land_number = %s,
                area = %s,
                declared_value = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id
            """,
            (
                land_key,
                land_id,
                land_key,
                district,
                section,
                subsection,
                land_number,
                values.get("area"),
                values.get("declared_value"),
                land_id,
            ),
        ).fetchone()

    def _save_record_with_conn(
        self, conn, user, values, record_id=None, *, write_audit=True
    ):
        previous_address = None
        if record_id is not None:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (int(record_id),)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
            previous_address = self._record_address_before_update(
                conn, user, record_id
            )
        owner_id, land_id, encrypted = self._save_owner_and_land(
            conn, user, values
        )
        apply_record_urban_plan(conn, land_id, values.get("urban_plan_id"))
        if record_id is None:
            row = conn.execute(
                """
                INSERT INTO ownerships (
                    owner_id, land_id, registration_order, numerator,
                    denominator, ping, total_declared_value,
                    registration_reason, note, visit_log, name,
                    owner_name_override, external_id_override, address_override
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s)
                RETURNING id
                """,
                (
                    owner_id, land_id, values.get("registration_order"),
                    values.get("numerator"), values.get("denominator"),
                    values.get("ping"), values.get("total_declared_value"),
                    values.get("registration_reason"), encrypted.get("note"),
                    encrypted.get("visit_log"), encrypted.get("name"),
                    encrypted.get("owner_name"), encrypted.get("external_id"),
                    encrypted.get("address"),
                ),
            ).fetchone()
            saved_id = int(row["id"])
            action_type = "api_create_record"
            summary = f"Created ownership {saved_id}"
        else:
            saved_id = int(record_id)
            conn.execute(
                """
                UPDATE ownerships SET
                    owner_id = %s, land_id = %s, registration_order = %s,
                    numerator = %s, denominator = %s, ping = %s,
                    total_declared_value = %s, registration_reason = %s,
                    note = %s, visit_log = %s, name = %s,
                    owner_name_override = %s, external_id_override = %s,
                    address_override = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    owner_id, land_id, values.get("registration_order"),
                    values.get("numerator"), values.get("denominator"),
                    values.get("ping"), values.get("total_declared_value"),
                    values.get("registration_reason"), encrypted.get("note"),
                    encrypted.get("visit_log"), encrypted.get("name"),
                    encrypted.get("owner_name"), encrypted.get("external_id"),
                    encrypted.get("address"), saved_id,
                ),
            )
            action_type = "api_update_record"
            summary = f"Updated ownership {saved_id}"
            self._synchronize_location_address(
                conn,
                saved_id,
                previous_address,
                values.get("address"),
            )
        if write_audit:
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, %s, 'ownership', %s, %s)
                """,
                (user.id, user.username, action_type, saved_id, summary),
            )
        return saved_id

    def save_record(self, user, values, record_id=None):
        return self._record_write_with_identity_repair(
            lambda conn: self._save_record_with_conn(
                conn, user, values, record_id
            )
        )

    def save_record_with_change_logs(
        self, user, values, record_id, change_logs
    ):
        record_id = int(record_id)
        normalized_logs = [
            {**dict(item), "record_id": record_id} for item in change_logs
        ]
        def save_with_history(conn):
            saved_id = self._save_record_with_conn(
                conn, user, values, record_id=record_id
            )
            self._add_record_change_logs_with_conn(
                conn, user, normalized_logs
            )
            return saved_id

        return self._record_write_with_identity_repair(save_with_history)

    def import_records(
        self, user, items, source_file_name="import.xlsx", urban_plan_id=None
    ):
        items = [dict(item) for item in items]
        urban_plan_summary = None
        safe_name = Path(str(source_file_name or "import.xlsx")).name or "import.xlsx"
        inserted_ids = []
        updated_ids = []
        with self._connect() as conn:
            update_ids = sorted(
                {
                    int(item["record_id"])
                    for item in items
                    if item.get("record_id") is not None
                }
            )
            self._require_ids(conn, "ownerships", update_ids)
            update_snapshots = [
                snapshot for record_id in update_ids
                if (snapshot := self._capture_record_snapshot(conn, record_id))
            ]
            batch_row = conn.execute(
                """
                INSERT INTO import_batches (
                    source_file_name, total_rows, success_rows,
                    duplicate_rows, failed_rows, imported_by
                ) VALUES (%s, %s, 0, 0, 0, %s)
                RETURNING id
                """,
                (safe_name, len(items), user.id),
            ).fetchone()
            batch_id = int(batch_row["id"])
            for row_number, item in enumerate(items, start=1):
                record_id = item.get("record_id")
                values = dict(item["values"])
                saved_id = self._save_record_with_conn(
                    conn,
                    user,
                    values,
                    None if record_id is None else int(record_id),
                    write_audit=False,
                )
                if record_id is None:
                    inserted_ids.append(saved_id)
                else:
                    updated_ids.append(saved_id)
                protected_values = _encrypted_record(user, values)
                conn.execute(
                    """
                    INSERT INTO import_data (
                        batch_id, row_number, raw_values, processing_status
                    ) VALUES (%s, %s, %s::jsonb, 'success')
                    """,
                    (
                        batch_id,
                        row_number,
                        json.dumps(
                            {
                                "record_id": saved_id,
                                "mode": "insert" if record_id is None else "update",
                                "values": protected_values,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    ),
                )
            conn.execute(
                """
                UPDATE import_batches
                SET success_rows = %s
                WHERE id = %s
                """,
                (len(items), batch_id),
            )
            undo_payload = {
                "mode": "composite",
                "snapshots": update_snapshots,
                "inserted_record_ids": inserted_ids,
            }
            self._record_undo_with_conn(
                conn,
                user,
                "Excel 匯入" if source_file_name != "desktop-batch.xlsx" else "同地號批量新增",
                f"新增 {len(inserted_ids)} 筆，更新 {len(updated_ids)} 筆",
                undo_payload,
            )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id,
                    summary, detail
                ) VALUES (%s, %s, 'api_import_records', 'import_batch', %s, %s, %s::jsonb)
                """,
                (
                    user.id,
                    user.username,
                    batch_id,
                    f"Imported {len(inserted_ids)} and updated {len(updated_ids)} records",
                    json.dumps(
                        {
                            "source_file_name": safe_name,
                            "inserted_ids": inserted_ids,
                            "updated_ids": updated_ids,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            if urban_plan_id is not None:
                urban_plan_summary = assign_imported_lands(
                    conn, user, inserted_ids + updated_ids, urban_plan_id
                )
        result = {
            "batch_id": batch_id,
            "inserted_count": len(inserted_ids),
            "updated_count": len(updated_ids),
            "inserted_ids": inserted_ids,
            "updated_ids": updated_ids,
        }
        if urban_plan_summary is not None:
            result["urban_plan"] = urban_plan_summary
        return result

    def delete_record(self, user, record_id):
        record_id = int(record_id)
        with self._connect() as conn:
            row = conn.execute(
                self.RECORD_SELECT + " WHERE ownership.id = %s",
                (record_id,),
            ).fetchone()
            if row is None:
                raise KeyError(record_id)
            snapshot = self._capture_record_snapshot(conn, record_id)
            label = " / ".join(
                str(row.get(key) or "")
                for key in ("district", "section", "subsection", "land_number")
            ).strip(" / ") or f"ID {record_id}"
            conn.execute(
                """
                INSERT INTO recycle_bin (
                    entity_type, original_id, display_label, payload_json, deleted_by
                ) VALUES ('ownership', %s, %s, %s::jsonb, %s)
                """,
                (
                    record_id,
                    label,
                    json.dumps(snapshot, ensure_ascii=False, default=str),
                    user.username,
                ),
            )
            self._delete_record_dependencies(conn, [record_id])
            conn.execute("DELETE FROM ownerships WHERE id = %s", (record_id,))
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_delete_record', 'ownership', %s, %s)
                """,
                (user.id, user.username, record_id, f"Deleted ownership {record_id}"),
            )
        return True
