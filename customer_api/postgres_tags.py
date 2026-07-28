"""PostgreSQL tag and assignment workflows."""

import json

from customer_api.data_source_base import _row_dict


class PostgreSQLTagMixin:
    def list_tags(self, user):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tag.id, tag.name, tag.color, tag.created_at,
                       COUNT(link.ownership_id)::integer AS customer_count
                FROM tags tag
                LEFT JOIN ownership_tags link ON link.tag_id = tag.id
                GROUP BY tag.id
                ORDER BY LOWER(tag.name), tag.id
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def save_tag(self, user, name, color="", tag_id=None):
        name = str(name or "").strip()
        color = str(color or "").strip()
        if not name:
            raise ValueError("標籤名稱不可空白")
        with self._connect() as conn:
            duplicate = conn.execute(
                """
                SELECT id FROM tags
                WHERE name = %s AND (%s::bigint IS NULL OR id <> %s::bigint)
                """,
                (name, tag_id, tag_id),
            ).fetchone()
            if duplicate:
                raise ValueError("已有相同名稱的標籤")
            if tag_id is None:
                row = conn.execute(
                    "INSERT INTO tags (name, color) VALUES (%s, %s) RETURNING id",
                    (name, color or None),
                ).fetchone()
                action_type = "api_create_tag"
            else:
                row = conn.execute(
                    """
                    UPDATE tags SET name = %s, color = %s
                    WHERE id = %s RETURNING id
                    """,
                    (name, color or None, int(tag_id)),
                ).fetchone()
                if row is None:
                    raise KeyError(tag_id)
                action_type = "api_update_tag"
            saved_id = int(row["id"])
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, %s, 'tag', %s, %s)
                """,
                (user.id, user.username, action_type, saved_id, f"Saved tag {name}"),
            )
        return saved_id

    def delete_tag(self, user, tag_id):
        tag_id = int(tag_id)
        with self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM tags WHERE id = %s RETURNING name", (tag_id,)
            ).fetchone()
            if deleted:
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_delete_tag', 'tag', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        tag_id,
                        f"Deleted tag {deleted['name']}",
                    ),
                )
        return bool(deleted)

    @staticmethod
    def _normalize_ids(values):
        return sorted({int(value) for value in values})

    @staticmethod
    def _require_ids(conn, table, ids):
        ids = PostgreSQLTagMixin._normalize_ids(ids)
        if not ids:
            return
        rows = conn.execute(
            f"SELECT id FROM {table} WHERE id = ANY(%s)", (ids,)
        ).fetchall()
        if len(rows) != len(ids):
            raise KeyError(f"{table} contains missing ids")

    def get_record_tag_ids(self, user, record_id):
        del user
        record_id = int(record_id)
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            rows = conn.execute(
                "SELECT tag_id FROM ownership_tags WHERE ownership_id = %s",
                (record_id,),
            ).fetchall()
        return {int(row["tag_id"]) for row in rows}

    def set_record_tags(self, user, record_id, tag_ids):
        record_id = int(record_id)
        tag_ids = self._normalize_ids(tag_ids)
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            self._require_ids(conn, "tags", tag_ids)
            conn.execute(
                "DELETE FROM ownership_tags WHERE ownership_id = %s", (record_id,)
            )
            if tag_ids:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO ownership_tags (ownership_id, tag_id)
                        VALUES (%s, %s) ON CONFLICT DO NOTHING
                        """,
                        [(record_id, tag_id) for tag_id in tag_ids],
                    )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_set_record_tags', 'ownership', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    record_id,
                    f"Set {len(tag_ids)} tags on ownership {record_id}",
                ),
            )
        return len(tag_ids)

    def set_records_tags(self, user, record_ids, tag_ids, mode="add"):
        record_ids = self._normalize_ids(record_ids)
        tag_ids = self._normalize_ids(tag_ids)
        mode = str(mode or "add")
        if mode not in {"add", "remove", "replace"}:
            raise ValueError("不支援的標籤批量模式")
        if not record_ids:
            return 0
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", record_ids)
            self._require_ids(conn, "tags", tag_ids)
            if mode == "replace":
                conn.execute(
                    "DELETE FROM ownership_tags WHERE ownership_id = ANY(%s)",
                    (record_ids,),
                )
            if mode in {"add", "replace"} and tag_ids:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO ownership_tags (ownership_id, tag_id)
                        VALUES (%s, %s) ON CONFLICT DO NOTHING
                        """,
                        [
                            (record_id, tag_id)
                            for record_id in record_ids
                            for tag_id in tag_ids
                        ],
                    )
            elif mode == "remove" and tag_ids:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        DELETE FROM ownership_tags
                        WHERE ownership_id = %s AND tag_id = %s
                        """,
                        [
                            (record_id, tag_id)
                            for record_id in record_ids
                            for tag_id in tag_ids
                        ],
                    )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, summary, detail
                ) VALUES (%s, %s, 'api_set_records_tags', 'ownership', %s, %s::jsonb)
                """,
                (
                    user.id,
                    user.username,
                    f"Updated tags on {len(record_ids)} ownerships",
                    json.dumps(
                        {"mode": mode, "record_ids": record_ids, "tag_ids": tag_ids}
                    ),
                ),
            )
        return len(record_ids)
