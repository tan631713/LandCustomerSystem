"""PostgreSQL implementations for desktop productivity features."""

import hashlib
from pathlib import Path

from customer_api.data_source_base import _row_dict
from customer_api.field_visit_routing import validate_coordinate
from customer_api.field_visit_service import location_address_fingerprint
from customer_repository import CustomerRepository, normalize_watch_name
from customer_security import decrypt_value, make_fernet


class PostgreSQLDesktopFeatureMixin:
    @staticmethod
    def _execute_many(conn, query, entries):
        """Run a PostgreSQL batch through a cursor (psycopg 3 API)."""

        with conn.cursor() as cursor:
            cursor.executemany(query, entries)

    def list_record_change_logs(self, user, record_id, limit=300):
        del user
        record_id = int(record_id)
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            rows = conn.execute(
                """
                SELECT id, ownership_id AS customer_id, action_type, field_key,
                       field_label, old_value, new_value, created_at
                FROM record_change_logs
                WHERE ownership_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (record_id, max(1, min(int(limit), 1000))),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    @staticmethod
    def _record_change_log_entries(items):
        entries = []
        for item in items:
            entries.append(
                (
                    int(item["record_id"]),
                    str(item.get("action_type") or "修改資料"),
                    str(item["field_key"]),
                    str(item.get("field_label") or item["field_key"]),
                    item.get("old_value"),
                    item.get("new_value"),
                )
            )
        return entries

    def _add_record_change_logs_with_conn(self, conn, user, items):
        entries = self._record_change_log_entries(items)
        if not entries:
            return 0
        self._require_ids(conn, "ownerships", [row[0] for row in entries])
        self._execute_many(
            conn,
            """
            INSERT INTO record_change_logs (
                ownership_id, action_type, field_key, field_label,
                old_value, new_value
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            entries,
        )
        conn.execute(
            """
            INSERT INTO operation_logs (
                action_type, summary, detail, actor_username
            ) VALUES ('修改歷史', %s, %s, %s)
            """,
            (
                f"寫入 {len(entries)} 筆修改歷史",
                "Desktop API",
                user.username,
            ),
        )
        return len(entries)

    def add_record_change_logs(self, user, items):
        with self._connect() as conn:
            return self._add_record_change_logs_with_conn(conn, user, items)

    def list_custom_fields(self, user):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, field_key, label, created_at
                FROM custom_fields ORDER BY id
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def save_custom_field(self, user, label, field_key=None, field_id=None):
        del user
        label = str(label or "").strip()
        if not label:
            raise ValueError("欄位名稱不可空白")
        normalized_key = CustomerRepository.normalize_custom_field_key(
            label, field_key
        )
        with self._connect() as conn:
            if field_id is None:
                row = conn.execute(
                    """
                    INSERT INTO custom_fields (field_key, label)
                    VALUES (%s, %s) RETURNING id
                    """,
                    (normalized_key, label),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    UPDATE custom_fields SET field_key = %s, label = %s
                    WHERE id = %s RETURNING id
                    """,
                    (normalized_key, label, int(field_id)),
                ).fetchone()
                if row is None:
                    raise KeyError(field_id)
        return int(row["id"])

    def delete_custom_field(self, user, field_id):
        del user
        with self._connect() as conn:
            row = conn.execute(
                "DELETE FROM custom_fields WHERE id = %s RETURNING id",
                (int(field_id),),
            ).fetchone()
        return row is not None

    def get_record_custom_values(self, user, record_id):
        del user
        record_id = int(record_id)
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            rows = conn.execute(
                """
                SELECT field_id, value FROM ownership_custom_values
                WHERE ownership_id = %s
                """,
                (record_id,),
            ).fetchall()
        return {int(row["field_id"]): row.get("value") for row in rows}

    @staticmethod
    def _clean_custom_values(values):
        return {
            int(field_id): str(value or "").strip()
            for field_id, value in dict(values or {}).items()
        }

    def set_record_custom_values(self, user, record_id, values):
        del user
        record_id = int(record_id)
        cleaned = self._clean_custom_values(values)
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            if cleaned:
                self._require_ids(conn, "custom_fields", cleaned)
            conn.execute(
                "DELETE FROM ownership_custom_values WHERE ownership_id = %s",
                (record_id,),
            )
            entries = [
                (record_id, field_id, value)
                for field_id, value in cleaned.items()
                if value
            ]
            if entries:
                self._execute_many(
                    conn,
                    """
                    INSERT INTO ownership_custom_values (
                        ownership_id, field_id, value
                    ) VALUES (%s, %s, %s)
                    """,
                    entries,
                )
        return len(entries)

    def set_records_custom_values(self, user, record_ids, values):
        del user
        record_ids = sorted({int(value) for value in record_ids})
        cleaned = self._clean_custom_values(values)
        if not record_ids or not cleaned:
            return 0
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", record_ids)
            self._require_ids(conn, "custom_fields", cleaned)
            for record_id in record_ids:
                for field_id, value in cleaned.items():
                    if value:
                        conn.execute(
                            """
                            INSERT INTO ownership_custom_values (
                                ownership_id, field_id, value, updated_at
                            ) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT (ownership_id, field_id) DO UPDATE SET
                                value = EXCLUDED.value,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            (record_id, field_id, value),
                        )
                    else:
                        conn.execute(
                            """
                            DELETE FROM ownership_custom_values
                            WHERE ownership_id = %s AND field_id = %s
                            """,
                            (record_id, field_id),
                        )
        return len(record_ids)

    def list_text_templates(self, user, template_type=None):
        del user
        query = """
            SELECT id, template_type, title, content, created_at, updated_at
            FROM text_templates
        """
        parameters = ()
        if template_type:
            query += " WHERE template_type = %s"
            parameters = (str(template_type),)
        query += " ORDER BY template_type, LOWER(title), id"
        with self._connect() as conn:
            rows = conn.execute(query, parameters).fetchall()
        return [_row_dict(row) for row in rows]

    def save_text_template(
        self, user, title, content, template_type="note", template_id=None
    ):
        del user
        title = str(title or "").strip()
        content = str(content or "").strip()
        template_type = str(template_type or "note").strip() or "note"
        if not title or not content:
            raise ValueError("範本名稱與內容不可空白")
        with self._connect() as conn:
            if template_id is None:
                row = conn.execute(
                    """
                    INSERT INTO text_templates (template_type, title, content)
                    VALUES (%s, %s, %s) RETURNING id
                    """,
                    (template_type, title, content),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    UPDATE text_templates SET template_type = %s, title = %s,
                        content = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s RETURNING id
                    """,
                    (template_type, title, content, int(template_id)),
                ).fetchone()
                if row is None:
                    raise KeyError(template_id)
        return int(row["id"])

    def delete_text_template(self, user, template_id):
        del user
        with self._connect() as conn:
            row = conn.execute(
                "DELETE FROM text_templates WHERE id = %s RETURNING id",
                (int(template_id),),
            ).fetchone()
        return row is not None

    def list_watchlist(self, user):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, note FROM watchlist ORDER BY LOWER(name), id"
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def replace_watchlist(self, user, items):
        cleaned = []
        seen = set()
        for item in items:
            name = str(item.get("name") or "").strip()
            note = str(item.get("note") or "").strip()
            normalized = normalize_watch_name(name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append((name, normalized, note or None))
        with self._connect() as conn:
            conn.execute("DELETE FROM watchlist")
            if cleaned:
                self._execute_many(
                    conn,
                    """
                    INSERT INTO watchlist (name, normalized_name, note)
                    VALUES (%s, %s, %s)
                    """,
                    cleaned,
                )
            conn.execute(
                """
                INSERT INTO operation_logs (
                    action_type, summary, detail, actor_username
                ) VALUES ('注意名單', %s, '', %s)
                """,
                (f"更新 {len(cleaned)} 筆注意名單", user.username),
            )
        return len(cleaned)

    def list_operation_logs(self, user, limit=300):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, action_type, summary, detail, actor_username, created_at
                FROM operation_logs ORDER BY id DESC LIMIT %s
                """,
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def add_operation_log(self, user, action_type, summary, detail=""):
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO operation_logs (
                    action_type, summary, detail, actor_username
                ) VALUES (%s, %s, %s, %s) RETURNING id
                """,
                (
                    str(action_type),
                    str(summary),
                    str(detail or "") or None,
                    user.username,
                ),
            ).fetchone()
        return int(row["id"])

    def list_record_locations(self, user):
        fernet = make_fernet(user.data_key)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT location.ownership_id AS customer_id, location.latitude,
                       location.longitude, location.source,
                       location.geocode_status, location.geocode_source,
                       location.geocoded_at, location.geocode_error,
                       location.updated_at,
                       land.district, land.section, land.land_number,
                       COALESCE(ownership.owner_name_override, owner.owner_name) AS owner_name,
                       COALESCE(ownership.address_override, owner.address) AS address
                FROM ownership_locations location
                JOIN ownerships ownership ON ownership.id = location.ownership_id
                JOIN lands land ON land.id = ownership.land_id
                JOIN owners owner ON owner.id = ownership.owner_id
                ORDER BY land.district, land.section, land.land_number
                """
            ).fetchall()
        results = []
        for row in rows:
            item = _row_dict(row)
            item["owner_name"] = decrypt_value(fernet, item.get("owner_name"))
            item["address"] = decrypt_value(fernet, item.get("address"))
            results.append(item)
        return results

    def set_record_location(
        self, user, record_id, latitude, longitude, source="manual"
    ):
        record_id = int(record_id)
        latitude, longitude = validate_coordinate(latitude, longitude)
        location_source = str(source or "manual").strip() or "manual"
        geocode_status = (
            "manual" if location_source.casefold() == "manual" else "success"
        )
        fernet = make_fernet(user.data_key)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(ownership.address_override, owner.address) AS address
                FROM ownerships ownership
                JOIN owners owner ON owner.id = ownership.owner_id
                WHERE ownership.id = %s
                """,
                (record_id,),
            ).fetchone()
            if row is None:
                raise KeyError(record_id)
            address = decrypt_value(fernet, row.get("address"))
            conn.execute(
                """
                INSERT INTO ownership_locations (
                    ownership_id, latitude, longitude, source,
                    geocode_status, geocode_source, geocoded_at,
                    geocode_error, address_fingerprint
                ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, NULL, %s)
                ON CONFLICT (ownership_id) DO UPDATE SET
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    source = EXCLUDED.source,
                    geocode_status = EXCLUDED.geocode_status,
                    geocode_source = EXCLUDED.geocode_source,
                    geocoded_at = CURRENT_TIMESTAMP,
                    geocode_error = NULL,
                    address_fingerprint = EXCLUDED.address_fingerprint,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record_id,
                    latitude,
                    longitude,
                    location_source,
                    geocode_status,
                    location_source,
                    location_address_fingerprint(address),
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_set_record_location', 'ownership', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    record_id,
                    f"Updated manual location for ownership {record_id}",
                ),
            )
        return record_id

    def ignored_duplicate_pairs(self, user):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT left_ownership_id, right_ownership_id
                FROM duplicate_reviews WHERE decision = 'ignored'
                """
            ).fetchall()
        return [
            (int(row["left_ownership_id"]), int(row["right_ownership_id"]))
            for row in rows
        ]

    def ignore_duplicate_pair(self, user, left_record_id, right_record_id):
        del user
        left_record_id, right_record_id = sorted(
            (int(left_record_id), int(right_record_id))
        )
        with self._connect() as conn:
            self._require_ids(
                conn, "ownerships", [left_record_id, right_record_id]
            )
            conn.execute(
                """
                INSERT INTO duplicate_reviews (
                    left_ownership_id, right_ownership_id, decision, reviewed_at
                ) VALUES (%s, %s, 'ignored', CURRENT_TIMESTAMP)
                ON CONFLICT (left_ownership_id, right_ownership_id) DO UPDATE SET
                    decision = 'ignored', reviewed_at = CURRENT_TIMESTAMP
                """,
                (left_record_id, right_record_id),
            )
        return True

    def verify_managed_attachments(self, user):
        del user
        results = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, storage_path, original_name, sha256
                FROM attachments WHERE status = 'managed' ORDER BY id
                """
            ).fetchall()
            for row in rows:
                path = Path(str(row.get("storage_path") or ""))
                state = "正常"
                current_hash = ""
                if not path.is_file():
                    state = "遺失"
                else:
                    digest = hashlib.sha256()
                    with path.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    current_hash = digest.hexdigest()
                    if row.get("sha256") and current_hash != row["sha256"]:
                        state = "內容已變更"
                conn.execute(
                    "UPDATE attachments SET status = %s WHERE id = %s",
                    ("managed" if state == "正常" else state, row["id"]),
                )
                results.append(
                    {
                        "id": int(row["id"]),
                        "name": row.get("original_name") or path.name,
                        "path": str(path),
                        "state": state,
                        "sha256": current_hash or row.get("sha256") or "",
                    }
                )
        return results
