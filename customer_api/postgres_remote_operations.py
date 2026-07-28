"""Transactional PostgreSQL workflows used by the full desktop client."""

import json
import os

from customer_api.data_source_base import _decrypt_record, _row_dict
from customer_security import (
    derive_encryption_key,
    encrypt_value,
    hash_password,
    make_fernet,
    verify_password,
)


class PostgreSQLRemoteOperationMixin:
    _SNAPSHOT_QUERIES = {
        "project_ownerships": "SELECT * FROM project_ownerships WHERE ownership_id=%s",
        "ownership_tags": "SELECT * FROM ownership_tags WHERE ownership_id=%s",
        "ownership_custom_values": "SELECT * FROM ownership_custom_values WHERE ownership_id=%s",
        "contact_logs": "SELECT * FROM contact_logs WHERE ownership_id=%s",
        "attachments": "SELECT * FROM attachments WHERE ownership_id=%s",
        "follow_up_reminders": "SELECT * FROM follow_up_reminders WHERE ownership_id=%s",
        "record_change_logs": "SELECT * FROM record_change_logs WHERE ownership_id=%s",
        "ownership_locations": "SELECT * FROM ownership_locations WHERE ownership_id=%s",
    }

    def _capture_record_snapshot(self, conn, record_id):
        record_id = int(record_id)
        row = conn.execute(
            self.RECORD_SELECT + " WHERE ownership.id = %s", (record_id,)
        ).fetchone()
        if row is None:
            return None
        related = {
            name: [_row_dict(item) for item in conn.execute(query, (record_id,)).fetchall()]
            for name, query in self._SNAPSHOT_QUERIES.items()
        }
        related["duplicate_reviews"] = [
            _row_dict(item)
            for item in conn.execute(
                """
                SELECT * FROM duplicate_reviews
                WHERE left_ownership_id=%s OR right_ownership_id=%s
                """,
                (record_id, record_id),
            ).fetchall()
        ]
        field_visit_items = [
            _row_dict(item)
            for item in conn.execute(
                """
                SELECT * FROM field_visit_route_items
                WHERE ownership_id=%s ORDER BY id
                """,
                (record_id,),
            ).fetchall()
        ]
        related["field_visit_route_items"] = field_visit_items
        route_item_ids = [int(item["id"]) for item in field_visit_items]
        related["field_visit_status_history"] = (
            [
                _row_dict(item)
                for item in conn.execute(
                    """
                    SELECT * FROM field_visit_status_history
                    WHERE route_item_id=ANY(%s) ORDER BY id
                    """,
                    (route_item_ids,),
                ).fetchall()
            ]
            if route_item_ids
            else []
        )
        return {"record": _row_dict(row), "related": related}

    def _delete_record_dependencies(self, conn, record_ids):
        ids = self._normalize_ids(record_ids)
        if not ids:
            return 0
        rows = conn.execute(
            """
            DELETE FROM field_visit_route_items
            WHERE ownership_id=ANY(%s)
            RETURNING id
            """,
            (ids,),
        ).fetchall()
        return len(rows)

    def capture_record_snapshots(self, user, record_ids):
        del user
        with self._connect() as conn:
            return [
                snapshot for record_id in self._normalize_ids(record_ids)
                if (snapshot := self._capture_record_snapshot(conn, record_id))
            ]

    @staticmethod
    def _insert_rows(conn, table_name, rows, ownership_id, *, conflict="NOTHING"):
        column_map = {
            "project_ownerships": ("project_id", "ownership_id", "created_at"),
            "ownership_tags": ("ownership_id", "tag_id", "created_at"),
            "ownership_custom_values": ("ownership_id", "field_id", "value", "updated_at"),
            "attachments": (
                "id", "owner_id", "land_id", "project_id", "storage_path",
                "original_name", "media_type", "size_bytes", "sha256", "created_by",
                "created_at", "legacy_attachment_id", "ownership_id", "file_path",
                "description", "status", "version", "category", "contact_log_id",
                "field_visit_route_item_id",
            ),
            "contact_logs": (
                "id", "legacy_contact_log_id", "ownership_id", "contact_date",
                "method", "result", "next_follow_up", "note", "created_by", "created_at",
                "contacted_at", "latitude", "longitude", "field_visit_route_item_id",
            ),
            "follow_up_reminders": (
                "id", "ownership_id", "due_date", "status", "note", "created_at", "updated_at",
            ),
            "record_change_logs": (
                "id", "legacy_change_log_id", "ownership_id", "action_type", "field_key",
                "field_label", "old_value", "new_value", "created_at",
            ),
            "ownership_locations": (
                "ownership_id", "latitude", "longitude", "source", "updated_at",
            ),
        }
        columns = column_map[table_name]
        placeholders = ", ".join(["%s"] * len(columns))
        sql = (
            f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT DO {conflict}"
        )
        for raw in rows:
            row = dict(raw)
            if "ownership_id" in columns:
                row["ownership_id"] = int(ownership_id)
            conn.execute(sql, tuple(row.get(column) for column in columns))

    @staticmethod
    def _restore_field_visit_snapshot(conn, related, ownership_id):
        restored_item_ids = set()
        for raw_item in related.get("field_visit_route_items", []):
            item = dict(raw_item)
            route_id = int(item["route_id"])
            if conn.execute(
                "SELECT 1 FROM field_visit_routes WHERE id=%s", (route_id,)
            ).fetchone() is None:
                continue
            if conn.execute(
                """
                SELECT 1 FROM field_visit_route_items
                WHERE id=%s OR (route_id=%s AND ownership_id=%s)
                """,
                (int(item["id"]), route_id, int(ownership_id)),
            ).fetchone() is not None:
                continue
            route_order = int(item.get("route_order") or 1)
            if conn.execute(
                """
                SELECT 1 FROM field_visit_route_items
                WHERE route_id=%s AND route_order=%s
                """,
                (route_id, route_order),
            ).fetchone() is not None:
                order_row = conn.execute(
                    """
                    SELECT COALESCE(MAX(route_order), 0) + 1 AS route_order
                    FROM field_visit_route_items WHERE route_id=%s
                    """,
                    (route_id,),
                ).fetchone()
                route_order = int(order_row["route_order"])
            restored = conn.execute(
                """
                INSERT INTO field_visit_route_items (
                    id, route_id, owner_id, ownership_id, land_id, route_order,
                    status, priority, is_order_locked, estimated_distance_km,
                    arrived_at, completed_at, postponed_until, note,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    COALESCE(%s, CURRENT_TIMESTAMP),
                    COALESCE(%s, CURRENT_TIMESTAMP)
                )
                RETURNING id
                """,
                (
                    int(item["id"]),
                    route_id,
                    int(item["owner_id"]),
                    int(ownership_id),
                    int(item["land_id"]),
                    route_order,
                    item.get("status") or "planned",
                    int(item.get("priority") or 0),
                    bool(item.get("is_order_locked")),
                    item.get("estimated_distance_km"),
                    item.get("arrived_at"),
                    item.get("completed_at"),
                    item.get("postponed_until"),
                    item.get("note"),
                    item.get("created_at"),
                    item.get("updated_at"),
                ),
            ).fetchone()
            if restored is not None:
                restored_item_ids.add(int(restored["id"]))

        for raw_history in related.get("field_visit_status_history", []):
            history = dict(raw_history)
            route_item_id = int(history["route_item_id"])
            if route_item_id not in restored_item_ids:
                continue
            conn.execute(
                """
                INSERT INTO field_visit_status_history (
                    id, route_item_id, old_status, new_status, user_id,
                    latitude, longitude, note, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP)
                )
                ON CONFLICT DO NOTHING
                """,
                (
                    int(history["id"]),
                    route_item_id,
                    history.get("old_status"),
                    history.get("new_status") or "planned",
                    history.get("user_id"),
                    history.get("latitude"),
                    history.get("longitude"),
                    history.get("note"),
                    history.get("created_at"),
                ),
            )
        return restored_item_ids

    def _restore_record_snapshot(self, conn, user, snapshot):
        raw = dict(snapshot.get("record") or {})
        if not raw:
            return None
        original_id = int(raw["id"])
        plain = _decrypt_record(raw, user)
        owner_id, land_id, encrypted = self._save_owner_and_land(conn, user, plain)
        self._delete_record_dependencies(conn, [original_id])
        conn.execute("DELETE FROM ownerships WHERE id=%s", (original_id,))
        conn.execute(
            """
            INSERT INTO ownerships (
                id, owner_id, land_id, registration_order, numerator, denominator,
                ping, total_declared_value, registration_reason, note, visit_log,
                name, owner_name_override, external_id_override, address_override,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s,
                      COALESCE(%s, CURRENT_TIMESTAMP), COALESCE(%s, CURRENT_TIMESTAMP))
            """,
            (
                original_id, owner_id, land_id, raw.get("registration_order"),
                raw.get("numerator"), raw.get("denominator"), raw.get("ping"),
                raw.get("total_declared_value"), raw.get("registration_reason"),
                encrypted.get("note"), encrypted.get("visit_log"), encrypted.get("name"),
                encrypted.get("owner_name"), encrypted.get("external_id"),
                encrypted.get("address"),
                raw.get("created_at"), raw.get("updated_at"),
            ),
        )
        related = dict(snapshot.get("related") or {})
        self._restore_field_visit_snapshot(conn, related, original_id)
        for table_name in self._SNAPSHOT_QUERIES:
            self._insert_rows(
                conn, table_name, related.get(table_name, []), original_id
            )
        for project_id in {
            int(row["project_id"])
            for row in related.get("project_ownerships", [])
        }:
            self._sync_project_dimension_links(conn, project_id)
        for review in related.get("duplicate_reviews", []):
            left_id = int(review["left_ownership_id"])
            right_id = int(review["right_ownership_id"])
            exists = conn.execute(
                "SELECT COUNT(*) AS count FROM ownerships WHERE id=ANY(%s)",
                ([left_id, right_id],),
            ).fetchone()
            if int(exists["count"]) == 2:
                conn.execute(
                    """
                    INSERT INTO duplicate_reviews (
                        left_ownership_id, right_ownership_id, decision, reviewed_at
                    ) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                    """,
                    (left_id, right_id, review.get("decision"), review.get("reviewed_at")),
                )
        return original_id

    def list_recycle_bin(self, user, limit=1000):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, entity_type, original_id, display_label, deleted_by, deleted_at
                FROM recycle_bin ORDER BY id DESC LIMIT %s
                """,
                (int(limit),),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def restore_recycle_items(self, user, recycle_ids):
        restored = []
        with self._connect() as conn:
            for recycle_id in self._normalize_ids(recycle_ids):
                row = conn.execute(
                    "SELECT payload_json FROM recycle_bin WHERE id=%s", (recycle_id,)
                ).fetchone()
                if row is None:
                    continue
                record_id = self._restore_record_snapshot(conn, user, row["payload_json"])
                if record_id is not None:
                    restored.append(record_id)
                    conn.execute("DELETE FROM recycle_bin WHERE id=%s", (recycle_id,))
        return restored

    def purge_recycle_items(self, user, recycle_ids=None):
        del user
        with self._connect() as conn:
            if recycle_ids is None:
                rows = conn.execute("DELETE FROM recycle_bin RETURNING id").fetchall()
            else:
                ids = self._normalize_ids(recycle_ids)
                rows = conn.execute(
                    "DELETE FROM recycle_bin WHERE id=ANY(%s) RETURNING id", (ids,)
                ).fetchall() if ids else []
        return len(rows)

    def _record_undo_with_conn(self, conn, user, operation_type, summary, payload):
        row = conn.execute(
            """
            INSERT INTO undo_operations (
                operation_type, summary, payload_json, actor_username
            ) VALUES (%s, %s, %s::jsonb, %s) RETURNING id
            """,
            (
                str(operation_type), str(summary),
                json.dumps(payload, ensure_ascii=False, default=str), user.username,
            ),
        ).fetchone()
        return int(row["id"])

    def record_customer_undo(self, user, operation_type, record_ids, summary):
        with self._connect() as conn:
            snapshots = [
                snapshot for record_id in self._normalize_ids(record_ids)
                if (snapshot := self._capture_record_snapshot(conn, record_id))
            ]
            if not snapshots:
                return None
            return self._record_undo_with_conn(
                conn, user, operation_type, summary,
                {"mode": "restore", "snapshots": snapshots},
            )

    def record_insert_undo(self, user, operation_type, record_ids, summary):
        ids = self._normalize_ids(record_ids)
        if not ids:
            return None
        with self._connect() as conn:
            return self._record_undo_with_conn(
                conn, user, operation_type, summary,
                {"mode": "delete_inserted", "record_ids": ids},
            )

    def list_undo_operations(self, user, limit=100):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, operation_type, summary, actor_username, status,
                       created_at, undone_at
                FROM undo_operations ORDER BY id DESC LIMIT %s
                """,
                (int(limit),),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def undo_operation(self, user, operation_id=None):
        with self._connect() as conn:
            if operation_id is None:
                row = conn.execute(
                    """
                    SELECT * FROM undo_operations WHERE status='available'
                    ORDER BY id DESC LIMIT 1 FOR UPDATE
                    """
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM undo_operations
                    WHERE id=%s AND status='available' FOR UPDATE
                    """,
                    (int(operation_id),),
                ).fetchone()
            if row is None:
                return None
            payload = dict(row["payload_json"])
            mode = payload.get("mode")
            if mode in {"delete_inserted", "composite"}:
                ids = payload.get("record_ids") or payload.get("inserted_record_ids") or []
                if ids:
                    normalized_ids = self._normalize_ids(ids)
                    self._delete_record_dependencies(conn, normalized_ids)
                    conn.execute(
                        "DELETE FROM ownerships WHERE id=ANY(%s)",
                        (normalized_ids,),
                    )
            restored = []
            if mode in {"restore", "composite"}:
                for snapshot in payload.get("snapshots", []):
                    restored_id = self._restore_record_snapshot(conn, user, snapshot)
                    if restored_id is not None:
                        restored.append(restored_id)
            if mode not in {"restore", "delete_inserted", "composite"}:
                raise ValueError("不支援的復原資料格式")
            conn.execute(
                """
                UPDATE undo_operations SET status='undone', undone_at=CURRENT_TIMESTAMP
                WHERE id=%s
                """,
                (row["id"],),
            )
        return {"operation_id": int(row["id"]), "summary": str(row["summary"]), "restored_ids": restored}

    def merge_records(self, user, primary_id, secondary_id, values):
        primary_id, secondary_id = int(primary_id), int(secondary_id)
        if primary_id == secondary_id:
            raise ValueError("必須選擇兩筆不同資料")
        with self._connect() as conn:
            snapshots = [
                self._capture_record_snapshot(conn, primary_id),
                self._capture_record_snapshot(conn, secondary_id),
            ]
            if any(snapshot is None for snapshot in snapshots):
                raise KeyError("record")
            self._record_undo_with_conn(
                conn, user, "合併資料", f"合併 ID {primary_id} 與 {secondary_id}",
                {"mode": "restore", "snapshots": snapshots},
            )
            affected_projects = [
                int(row["project_id"])
                for row in conn.execute(
                    """
                    SELECT DISTINCT project_id FROM project_ownerships
                    WHERE ownership_id=ANY(%s)
                    """,
                    ([primary_id, secondary_id],),
                ).fetchall()
            ]
            self._save_record_with_conn(conn, user, values, primary_id, write_audit=False)
            conn.execute(
                """
                INSERT INTO project_ownerships (project_id, ownership_id)
                SELECT project_id, %s FROM project_ownerships WHERE ownership_id=%s
                ON CONFLICT DO NOTHING
                """, (primary_id, secondary_id),
            )
            conn.execute(
                """
                INSERT INTO ownership_tags (ownership_id, tag_id)
                SELECT %s, tag_id FROM ownership_tags WHERE ownership_id=%s
                ON CONFLICT DO NOTHING
                """, (primary_id, secondary_id),
            )
            conn.execute(
                """
                INSERT INTO ownership_custom_values (ownership_id, field_id, value)
                SELECT %s, field_id, value FROM ownership_custom_values WHERE ownership_id=%s
                ON CONFLICT DO NOTHING
                """, (primary_id, secondary_id),
            )
            for table in ("attachments", "contact_logs", "record_change_logs"):
                conn.execute(
                    f"UPDATE {table} SET ownership_id=%s WHERE ownership_id=%s",
                    (primary_id, secondary_id),
                )
            conn.execute(
                """
                INSERT INTO follow_up_reminders (ownership_id, due_date, status, note)
                SELECT %s, due_date, status, note FROM follow_up_reminders
                WHERE ownership_id=%s ON CONFLICT DO NOTHING
                """, (primary_id, secondary_id),
            )
            conn.execute(
                """
                INSERT INTO ownership_locations (ownership_id, latitude, longitude, source)
                SELECT %s, latitude, longitude, source FROM ownership_locations
                WHERE ownership_id=%s ON CONFLICT DO NOTHING
                """, (primary_id, secondary_id),
            )
            conn.execute(
                "DELETE FROM duplicate_reviews WHERE left_ownership_id=%s OR right_ownership_id=%s",
                (secondary_id, secondary_id),
            )
            self._delete_record_dependencies(conn, [secondary_id])
            conn.execute("DELETE FROM ownerships WHERE id=%s", (secondary_id,))
            for project_id in affected_projects:
                self._sync_project_dimension_links(conn, project_id)
            conn.execute(
                """
                INSERT INTO audit_logs (user_id, actor, action_type, entity_type, entity_id, summary)
                VALUES (%s, %s, 'api_merge_records', 'ownership', %s, %s)
                """,
                (user.id, user.username, primary_id, f"Merged ownership {secondary_id} into {primary_id}"),
            )
        return primary_id

    def refresh_notifications(self, user, today_text):
        del user
        with self._connect() as conn:
            entries = []
            for row in conn.execute(
                """
                SELECT reminder.ownership_id AS id, reminder.due_date, reminder.status,
                       land.district, land.section, land.land_number
                FROM follow_up_reminders reminder
                JOIN ownerships ownership ON ownership.id=reminder.ownership_id
                JOIN lands land ON land.id=ownership.land_id
                WHERE reminder.status <> '完成' AND reminder.due_date <= %s
                """, (today_text,),
            ).fetchall():
                label = " ".join(str(row[key] or "") for key in ("district", "section", "land_number"))
                entries.append((f"follow_up:{row['id']}:{row['due_date']}", "追蹤", "地主追蹤到期", label, "逾期" if str(row["due_date"]) < str(today_text) else "提醒", "ownership", row["id"]))
            for table, category, related_type in (("projects", "案件", "project"), ("project_tasks", "任務", "project_task")):
                title_col = "title"
                rows = conn.execute(
                    f"SELECT id, {title_col} AS title, due_date, status FROM {table} WHERE status <> '完成' AND due_date <= %s",
                    (today_text,),
                ).fetchall()
                for row in rows:
                    entries.append((f"{related_type}:{row['id']}:{row['due_date']}", category, f"{category}期限到期", row["title"], "逾期" if str(row["due_date"]) < str(today_text) else "提醒", related_type, row["id"]))
            for entry in entries:
                conn.execute(
                    """
                    INSERT INTO notifications (
                        notification_key, category, title, detail, severity,
                        related_type, related_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (notification_key) DO UPDATE SET
                        title=EXCLUDED.title, detail=EXCLUDED.detail,
                        severity=EXCLUDED.severity
                    """, entry,
                )
        return len(entries)

    def list_notifications(self, user, include_read=False, limit=500):
        del user
        conditions = "dismissed_at IS NULL"
        if not include_read:
            conditions += " AND read_at IS NULL"
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, notification_key, category, title, detail, severity,
                       related_type, related_id, read_at, dismissed_at, created_at
                FROM notifications WHERE {conditions}
                ORDER BY CASE severity WHEN '逾期' THEN 0 ELSE 1 END, id DESC
                LIMIT %s
                """, (int(limit),),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def mark_notifications(self, user, notification_ids, action="read"):
        del user
        ids = self._normalize_ids(notification_ids)
        if not ids:
            return 0
        column = "dismissed_at" if action == "dismiss" else "read_at"
        with self._connect() as conn:
            rows = conn.execute(
                f"UPDATE notifications SET {column}=CURRENT_TIMESTAMP WHERE id=ANY(%s) RETURNING id",
                (ids,),
            ).fetchall()
        return len(rows)

    def list_users(self, user):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, username, display_name, role, active, created_at, last_login_at
                FROM users ORDER BY CASE WHEN username='admin' THEN 0 ELSE 1 END, username
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def create_user(self, user, username, password, role, display_name=None):
        username = str(username or "").strip()
        if not username or any(char.isspace() for char in username):
            raise ValueError("帳號不可空白或包含空白字元")
        password_salt, password_hash = hash_password(password)
        encryption_salt = os.urandom(16).hex()
        wrapped = make_fernet(derive_encryption_key(password, encryption_salt)).encrypt(user.data_key).decode("ascii")
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO users (
                    username, display_name, role, active, password_salt,
                    password_hash, encryption_salt, wrapped_data_key
                ) VALUES (%s, %s, %s, TRUE, %s, %s, %s, %s) RETURNING id
                """,
                (username, str(display_name or "").strip() or username, role, password_salt, password_hash, encryption_salt, wrapped),
            ).fetchone()
        return int(row["id"])

    def update_user(self, user, user_id, *, display_name=None, role=None, active=None):
        del user
        user_id = int(user_id)
        with self._connect() as conn:
            row = conn.execute("SELECT username FROM users WHERE id=%s", (user_id,)).fetchone()
            if row is None:
                raise KeyError(user_id)
            if row["username"] == "admin" and (active is False or role not in (None, "admin")):
                raise ValueError("不可停用主要 admin 帳號或移除其管理員權限")
            conn.execute(
                """
                UPDATE users SET
                    display_name=COALESCE(%s, display_name),
                    role=COALESCE(%s, role), active=COALESCE(%s, active)
                WHERE id=%s
                """,
                (str(display_name).strip() if display_name is not None else None, role, active, user_id),
            )
        return user_id

    def reset_user_password(self, user, user_id, new_password):
        password_salt, password_hash = hash_password(new_password)
        encryption_salt = os.urandom(16).hex()
        wrapped = make_fernet(derive_encryption_key(new_password, encryption_salt)).encrypt(user.data_key).decode("ascii")
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE users SET password_salt=%s, password_hash=%s,
                    encryption_salt=%s, wrapped_data_key=%s
                WHERE id=%s RETURNING id
                """,
                (password_salt, password_hash, encryption_salt, wrapped, int(user_id)),
            ).fetchone()
        if row is None:
            raise KeyError(user_id)
        return int(row["id"])

    def change_password(self, user, current_password, new_password):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_salt, password_hash FROM users WHERE id=%s AND active",
                (user.id,),
            ).fetchone()
            if row is None or not verify_password(current_password, row["password_salt"], row["password_hash"]):
                raise ValueError("目前密碼錯誤。")
        self.reset_user_password(user, user.id, new_password)
        return True

    def encrypt_existing_records(self, user):
        """Encrypt legacy plaintext sensitive fields using the shared data key."""

        fernet = make_fernet(user.data_key)
        owner_fields = ("owner_name", "external_id", "address", "note")
        ownership_fields = ("note", "visit_log", "name")
        affected_record_ids = set()
        updated_owner_rows = 0
        updated_ownership_rows = 0
        with self._connect() as conn:
            owner_rows = conn.execute(
                f"SELECT id, {', '.join(owner_fields)} FROM owners ORDER BY id"
            ).fetchall()
            for row in owner_rows:
                encrypted = {
                    field: encrypt_value(fernet, row[field]) for field in owner_fields
                }
                if all(encrypted[field] == row[field] for field in owner_fields):
                    continue
                conn.execute(
                    """
                    UPDATE owners SET owner_name=%s, external_id=%s, address=%s,
                        note=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s
                    """,
                    tuple(encrypted[field] for field in owner_fields) + (row["id"],),
                )
                updated_owner_rows += 1
                affected_record_ids.update(
                    int(item["id"])
                    for item in conn.execute(
                        "SELECT id FROM ownerships WHERE owner_id=%s", (row["id"],)
                    ).fetchall()
                )

            ownership_rows = conn.execute(
                f"SELECT id, {', '.join(ownership_fields)} FROM ownerships ORDER BY id"
            ).fetchall()
            for row in ownership_rows:
                encrypted = {
                    field: encrypt_value(fernet, row[field])
                    for field in ownership_fields
                }
                if all(encrypted[field] == row[field] for field in ownership_fields):
                    continue
                conn.execute(
                    """
                    UPDATE ownerships SET note=%s, visit_log=%s, name=%s,
                        updated_at=CURRENT_TIMESTAMP WHERE id=%s
                    """,
                    tuple(encrypted[field] for field in ownership_fields) + (row["id"],),
                )
                updated_ownership_rows += 1
                affected_record_ids.add(int(row["id"]))

            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, summary, detail
                ) VALUES (%s, %s, 'encrypt_existing_records', 'system', %s, %s::jsonb)
                """,
                (
                    user.id,
                    user.username,
                    f"Encrypted {len(affected_record_ids)} legacy ownership records",
                    json.dumps(
                        {
                            "updated_records": len(affected_record_ids),
                            "updated_owner_rows": updated_owner_rows,
                            "updated_ownership_rows": updated_ownership_rows,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        return {
            "updated_records": len(affected_record_ids),
            "updated_owner_rows": updated_owner_rows,
            "updated_ownership_rows": updated_ownership_rows,
        }

    def list_server_backup_targets(self, user):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, directory_path, enabled, last_success_at,
                       last_error, created_at, updated_at
                FROM server_backup_targets
                ORDER BY enabled DESC, name, id
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def save_server_backup_target(
        self, user, name, directory_path, enabled=True, target_id=None
    ):
        del user
        with self._connect() as conn:
            if target_id is None:
                row = conn.execute(
                    """
                    INSERT INTO server_backup_targets (name, directory_path, enabled)
                    VALUES (%s, %s, %s) RETURNING id
                    """,
                    (name, directory_path, bool(enabled)),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    UPDATE server_backup_targets
                    SET name=%s, directory_path=%s, enabled=%s,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=%s RETURNING id
                    """,
                    (name, directory_path, bool(enabled), int(target_id)),
                ).fetchone()
            if row is None:
                raise KeyError(target_id)
        return int(row["id"])

    def delete_server_backup_target(self, user, target_id):
        del user
        with self._connect() as conn:
            row = conn.execute(
                "DELETE FROM server_backup_targets WHERE id=%s RETURNING id",
                (int(target_id),),
            ).fetchone()
        return row is not None

    def update_server_backup_target_result(self, user, target_id, error=None):
        del user
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE server_backup_targets
                SET last_success_at=CASE WHEN %s IS NULL THEN CURRENT_TIMESTAMP
                                         ELSE last_success_at END,
                    last_error=%s, updated_at=CURRENT_TIMESTAMP
                WHERE id=%s
                """,
                (error, error, int(target_id)),
            )
