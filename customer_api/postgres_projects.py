"""PostgreSQL project and record-assignment workflows."""

import json

from customer_api.data_source_base import _row_dict


class PostgreSQLProjectMixin:
    def list_projects(self, user):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT project.id, project.title, project.status, project.note,
                       project.assigned_to_text AS assigned_to,
                       project.due_date, project.priority, project.next_action,
                       project.archived_at, project.created_at, project.updated_at,
                       COUNT(membership.ownership_id)::integer AS customer_count
                FROM projects project
                LEFT JOIN project_ownerships membership
                  ON membership.project_id = project.id
                GROUP BY project.id
                ORDER BY CASE WHEN project.archived_at IS NULL THEN 0 ELSE 1 END,
                         project.updated_at DESC, project.id DESC
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def save_project(
        self, user, title, status="進行中", note="", project_id=None, *,
        assigned_to=None, due_date=None, priority="一般", next_action=None,
        archived=False,
    ):
        title = str(title or "").strip()
        status = str(status or "進行中").strip() or "進行中"
        note = str(note or "").strip() or None
        assigned_to = str(assigned_to or "").strip() or None
        priority = str(priority or "一般").strip() or "一般"
        next_action = str(next_action or "").strip() or None
        if not title:
            raise ValueError("案件名稱不可空白")
        with self._connect() as conn:
            if project_id is None:
                row = conn.execute(
                    """
                    INSERT INTO projects (
                        title, status, note, assigned_to_text, due_date,
                        priority, next_action, archived_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s,
                              CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END)
                    RETURNING id
                    """,
                    (
                        title, status, note, assigned_to, due_date, priority,
                        next_action, bool(archived),
                    ),
                ).fetchone()
                action_type = "api_create_project"
            else:
                row = conn.execute(
                    """
                    UPDATE projects
                    SET title = %s, status = %s, note = %s,
                        assigned_to_text = %s, due_date = %s, priority = %s,
                        next_action = %s,
                        archived_at = CASE WHEN %s THEN
                            COALESCE(archived_at, CURRENT_TIMESTAMP) ELSE NULL END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id
                    """,
                    (
                        title, status, note, assigned_to, due_date, priority,
                        next_action, bool(archived), int(project_id),
                    ),
                ).fetchone()
                if row is None:
                    raise KeyError(project_id)
                action_type = "api_update_project"
            saved_id = int(row["id"])
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, %s, 'project', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    action_type,
                    saved_id,
                    f"Saved project {title}",
                ),
            )
        return saved_id

    def archive_project(self, user, project_id, archived=True):
        project_id = int(project_id)
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE projects
                SET archived_at = CASE WHEN %s THEN
                        COALESCE(archived_at, CURRENT_TIMESTAMP) ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id
                """,
                (bool(archived), project_id),
            ).fetchone()
            if row is None:
                raise KeyError(project_id)
        return project_id

    def list_project_tasks(self, user, project_id=None, include_completed=True):
        del user
        where = []
        values = []
        if project_id is not None:
            where.append("task.project_id = %s")
            values.append(int(project_id))
        if not include_completed:
            where.append("task.status <> '完成'")
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT task.id, task.project_id AS case_id, task.title,
                       task.assignee, task.due_date, task.status, task.priority,
                       task.checklist, task.created_at, task.updated_at,
                       project.title AS case_title
                FROM project_tasks task
                JOIN projects project ON project.id = task.project_id
                {where_sql}
                ORDER BY CASE WHEN task.status = '完成' THEN 1 ELSE 0 END,
                         CASE task.priority WHEN '緊急' THEN 0 WHEN '高' THEN 1 ELSE 2 END,
                         COALESCE(task.due_date, DATE '9999-12-31'), task.id DESC
                """,
                values,
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def save_project_task(self, user, project_id, title, *, assignee=None,
                          due_date=None, status="待處理", priority="一般",
                          checklist=None, task_id=None):
        project_id = int(project_id)
        title = str(title or "").strip()
        if not title:
            raise ValueError("任務名稱不可空白")
        values = (
            project_id, title, str(assignee or "").strip() or None, due_date,
            str(status or "待處理"), str(priority or "一般"),
            str(checklist or "").strip() or None,
        )
        with self._connect() as conn:
            self._require_ids(conn, "projects", [project_id])
            if task_id is None:
                row = conn.execute(
                    """
                    INSERT INTO project_tasks (
                        project_id, title, assignee, due_date, status,
                        priority, checklist
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    values,
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    UPDATE project_tasks
                    SET project_id=%s, title=%s, assignee=%s, due_date=%s,
                        status=%s, priority=%s, checklist=%s,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=%s RETURNING id
                    """,
                    (*values, int(task_id)),
                ).fetchone()
                if row is None:
                    raise KeyError(task_id)
        return int(row["id"])

    def delete_project_task(self, user, task_id):
        del user
        with self._connect() as conn:
            row = conn.execute(
                "DELETE FROM project_tasks WHERE id=%s RETURNING id",
                (int(task_id),),
            ).fetchone()
        return bool(row)

    def delete_project(self, user, project_id):
        project_id = int(project_id)
        with self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM projects WHERE id = %s RETURNING title",
                (project_id,),
            ).fetchone()
            if deleted:
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_delete_project', 'project', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        project_id,
                        f"Deleted project {deleted['title']}",
                    ),
                )
        return bool(deleted)

    @staticmethod
    def _sync_project_dimension_links(conn, project_id):
        project_id = int(project_id)
        conn.execute(
            "DELETE FROM project_owners WHERE project_id = %s", (project_id,)
        )
        conn.execute(
            """
            INSERT INTO project_owners (project_id, owner_id)
            SELECT %s, ownership.owner_id
            FROM project_ownerships membership
            JOIN ownerships ownership ON ownership.id = membership.ownership_id
            WHERE membership.project_id = %s
            GROUP BY ownership.owner_id
            """,
            (project_id, project_id),
        )
        conn.execute(
            "DELETE FROM project_lands WHERE project_id = %s", (project_id,)
        )
        conn.execute(
            """
            INSERT INTO project_lands (project_id, land_id)
            SELECT %s, ownership.land_id
            FROM project_ownerships membership
            JOIN ownerships ownership ON ownership.id = membership.ownership_id
            WHERE membership.project_id = %s
            GROUP BY ownership.land_id
            """,
            (project_id, project_id),
        )

    def _update_project_records(self, user, project_id, record_ids, mode):
        project_id = int(project_id)
        record_ids = self._normalize_ids(record_ids)
        if not record_ids:
            return 0
        with self._connect() as conn:
            self._require_ids(conn, "projects", [project_id])
            self._require_ids(conn, "ownerships", record_ids)
            if mode == "add":
                changed = conn.execute(
                    """
                    INSERT INTO project_ownerships (project_id, ownership_id)
                    SELECT %s, record_id
                    FROM UNNEST(%s::bigint[]) AS input(record_id)
                    ON CONFLICT DO NOTHING
                    RETURNING ownership_id
                    """,
                    (project_id, record_ids),
                ).fetchall()
                action_type = "api_add_project_records"
            elif mode == "remove":
                changed = conn.execute(
                    """
                    DELETE FROM project_ownerships
                    WHERE project_id = %s AND ownership_id = ANY(%s)
                    RETURNING ownership_id
                    """,
                    (project_id, record_ids),
                ).fetchall()
                action_type = "api_remove_project_records"
            else:
                raise ValueError("不支援的案件資料操作")
            self._sync_project_dimension_links(conn, project_id)
            conn.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (project_id,),
            )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id,
                    summary, detail
                ) VALUES (%s, %s, %s, 'project', %s, %s, %s::jsonb)
                """,
                (
                    user.id,
                    user.username,
                    action_type,
                    project_id,
                    f"Updated {len(changed)} project records",
                    json.dumps({"record_ids": record_ids}, ensure_ascii=False),
                ),
            )
        return len(changed)

    def add_records_to_project(self, user, project_id, record_ids):
        return self._update_project_records(
            user, project_id, record_ids, "add"
        )

    def remove_records_from_project(self, user, project_id, record_ids):
        return self._update_project_records(
            user, project_id, record_ids, "remove"
        )
