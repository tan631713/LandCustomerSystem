"""PostgreSQL contact-log and follow-up workflows."""

from customer_api.data_source_base import _decrypt_record, _row_dict


class PostgreSQLCollaborationMixin:
    def list_contact_logs(self, user, record_id):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, ownership_id AS customer_id, contact_date, method,
                       result, next_follow_up, note, created_at
                FROM contact_logs WHERE ownership_id = %s
                ORDER BY COALESCE(contact_date, created_at::date) DESC, id DESC
                """,
                (int(record_id),),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def add_contact_log(self, user, record_id, values):
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (int(record_id),)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
            row = conn.execute(
                """
                INSERT INTO contact_logs (
                    ownership_id, contact_date, method, result, next_follow_up,
                    note, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (
                    int(record_id),
                    values.get("contact_date") or None,
                    values.get("method") or None,
                    values.get("result") or None,
                    values.get("next_follow_up") or None,
                    values.get("note") or None,
                    user.id,
                ),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_create_contact_log', 'contact_log', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    int(row["id"]),
                    f"Created contact log for ownership {int(record_id)}",
                ),
            )
        return int(row["id"])

    def delete_contact_log(self, user, record_id, log_id):
        record_id = int(record_id)
        log_id = int(log_id)
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (record_id,)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
            deleted = conn.execute(
                """
                DELETE FROM contact_logs
                WHERE id = %s AND ownership_id = %s
                RETURNING id
                """,
                (log_id, record_id),
            ).fetchone()
            if deleted:
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_delete_contact_log', 'contact_log', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        log_id,
                        f"Deleted contact log from ownership {record_id}",
                    ),
                )
        return bool(deleted)

    def get_follow_up(self, user, record_id):
        del user
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, ownership_id AS customer_id, due_date, status, note,
                       created_at, updated_at
                FROM follow_up_reminders
                WHERE ownership_id = %s
                """,
                (int(record_id),),
            ).fetchone()
        return _row_dict(row) if row is not None else None

    def save_follow_up(self, user, record_id, values):
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (int(record_id),)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
            conn.execute(
                """
                INSERT INTO follow_up_reminders (ownership_id, due_date, status, note)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ownership_id) DO UPDATE SET
                    due_date = EXCLUDED.due_date,
                    status = EXCLUDED.status,
                    note = EXCLUDED.note,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(record_id),
                    values.get("due_date") or None,
                    values.get("status") or "未處理",
                    values.get("note") or None,
                ),
            )
            reminder = conn.execute(
                "SELECT id FROM follow_up_reminders WHERE ownership_id = %s",
                (int(record_id),),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_save_follow_up', 'follow_up', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    int(reminder["id"]),
                    f"Saved follow-up for ownership {int(record_id)}",
                ),
            )

    def delete_follow_up(self, user, record_id):
        record_id = int(record_id)
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (record_id,)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
            deleted = conn.execute(
                """
                DELETE FROM follow_up_reminders
                WHERE ownership_id = %s
                RETURNING id
                """,
                (record_id,),
            ).fetchone()
            if deleted:
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_delete_follow_up', 'follow_up', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        int(deleted["id"]),
                        f"Deleted follow-up from ownership {record_id}",
                    ),
                )
        return bool(deleted)

    def list_follow_ups(self, user, limit=500):
        sql = self.RECORD_SELECT + """
            WHERE reminder.id IS NOT NULL
            ORDER BY CASE WHEN reminder.status = '完成' THEN 1 ELSE 0 END,
                     reminder.due_date NULLS LAST, reminder.id DESC
            LIMIT %s
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (int(limit),)).fetchall()
            reminder_rows = conn.execute(
                """
                SELECT ownership_id, due_date, status, note
                FROM follow_up_reminders
                WHERE ownership_id = ANY(%s)
                """,
                ([int(row["id"]) for row in rows],),
            ).fetchall() if rows else []
        reminders = {
            int(row["ownership_id"]): _row_dict(row) for row in reminder_rows
        }
        items = []
        for row in rows:
            item = _decrypt_record(row, user)
            reminder = reminders.get(int(item["id"]), {})
            item["due_date"] = reminder.get("due_date") or ""
            item["status"] = reminder.get("status") or ""
            item["note"] = reminder.get("note") or ""
            items.append(item)
        return items
