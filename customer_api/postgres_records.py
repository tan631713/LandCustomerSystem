"""PostgreSQL customer-record persistence workflows."""

import json
from pathlib import Path

from customer_api.data_source_base import _decrypt_record, _encrypted_record, _filter_records, _row_dict
from customer_postgres_keys import land_key_for, owner_key_for


class PostgreSQLRecordMixin:
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
            INSERT INTO owners (owner_key, owner_name, external_id, address)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (owner_key) DO UPDATE SET
                owner_name = EXCLUDED.owner_name,
                external_id = EXCLUDED.external_id,
                address = EXCLUDED.address,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                owner_key_for(values, user.data_key),
                encrypted["owner_name"],
                encrypted.get("external_id"),
                encrypted.get("address"),
            ),
        ).fetchone()
        land_row = conn.execute(
            """
            INSERT INTO lands (
                land_key, district, section, land_number, area, declared_value
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (land_key) DO UPDATE SET
                district = EXCLUDED.district,
                section = EXCLUDED.section,
                land_number = EXCLUDED.land_number,
                area = EXCLUDED.area,
                declared_value = EXCLUDED.declared_value,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                land_key_for(values),
                values.get("district") or "",
                values.get("section") or "",
                values.get("land_number") or "",
                values.get("area"),
                values.get("declared_value"),
            ),
        ).fetchone()
        return int(owner_row["id"]), int(land_row["id"]), encrypted

    def _save_record_with_conn(
        self, conn, user, values, record_id=None, *, write_audit=True
    ):
        if record_id is not None:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (int(record_id),)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
        owner_id, land_id, encrypted = self._save_owner_and_land(
            conn, user, values
        )
        if record_id is None:
            row = conn.execute(
                """
                INSERT INTO ownerships (
                    owner_id, land_id, registration_order, numerator,
                    denominator, ping, total_declared_value,
                    registration_reason, note, visit_log, name
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    owner_id, land_id, values.get("registration_order"),
                    values.get("numerator"), values.get("denominator"),
                    values.get("ping"), values.get("total_declared_value"),
                    values.get("registration_reason"), encrypted.get("note"),
                    encrypted.get("visit_log"), encrypted.get("name"),
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
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    owner_id, land_id, values.get("registration_order"),
                    values.get("numerator"), values.get("denominator"),
                    values.get("ping"), values.get("total_declared_value"),
                    values.get("registration_reason"), encrypted.get("note"),
                    encrypted.get("visit_log"), encrypted.get("name"), saved_id,
                ),
            )
            action_type = "api_update_record"
            summary = f"Updated ownership {saved_id}"
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
        with self._connect() as conn:
            return self._save_record_with_conn(conn, user, values, record_id)

    def import_records(self, user, items, source_file_name="import.xlsx"):
        items = [dict(item) for item in items]
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
        return {
            "batch_id": batch_id,
            "inserted_count": len(inserted_ids),
            "updated_count": len(updated_ids),
            "inserted_ids": inserted_ids,
            "updated_ids": updated_ids,
        }

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
                for key in ("district", "section", "land_number")
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
