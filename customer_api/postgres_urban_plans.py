"""PostgreSQL urban plan (都市計畫) lists and their land assignments.

An urban plan is a named area such as 「龍岡都市計畫」. It is an attribute of a
*land* (every ownership on that land follows it), kept in a list the operator
maintains. Deleting a plan releases its lands back to 「未分類」 (NULL).

The record workflows (postgres_records.py) use the module-level helpers, so
they work without this mixin being part of the class.
"""

from customer_api.data_source_base import _row_dict

UNASSIGNED_LABEL = "未分類"
MAX_PLAN_NAME_LENGTH = 100
MAX_REPORTED_KEPT_LANDS = 500


def _land_ids(values):
    return sorted({int(value) for value in values})


def kept_lands(conn, land_ids, target):
    """Lands in `land_ids` that already belong to a plan other than `target`."""

    rows = conn.execute(
        """
        SELECT land.id, land.district, land.section, land.subsection,
               land.land_number, plan.name AS urban_plan_name
        FROM lands land
        JOIN urban_plans plan ON plan.id = land.urban_plan_id
        WHERE land.id = ANY(%s) AND land.urban_plan_id <> %s
        ORDER BY land.district, land.section, land.subsection, land.land_number
        LIMIT %s
        """,
        (land_ids, target, MAX_REPORTED_KEPT_LANDS),
    ).fetchall()
    return [_row_dict(row) for row in rows]


def audit_urban_plan(conn, user, action_type, entity_id, summary):
    conn.execute(
        """
        INSERT INTO audit_logs (
            user_id, actor, action_type, entity_type, entity_id, summary
        ) VALUES (%s, %s, %s, 'urban_plan', %s, %s)
        """,
        (user.id, user.username, action_type, entity_id, summary),
    )


def apply_record_urban_plan(conn, land_id, urban_plan_id):
    """Explicit plan choice on a saved record: None keeps it, 0 clears it,
    an id moves the whole land into that plan."""

    if urban_plan_id is None:
        return
    target = int(urban_plan_id) or None
    if target is not None:
        exists = conn.execute(
            "SELECT 1 AS found FROM urban_plans WHERE id = %s", (target,)
        ).fetchone()
        if not exists:
            raise ValueError("找不到這個都市計畫")
    conn.execute(
        """
        UPDATE lands
        SET urban_plan_id = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND urban_plan_id IS DISTINCT FROM %s
        """,
        (target, int(land_id), target),
    )


def assign_imported_lands(conn, user, ownership_ids, plan_id):
    """Import rule: lands without a plan join `plan_id`; lands that already
    belong to another plan are never overwritten, and are reported."""

    plan = conn.execute(
        "SELECT id, name FROM urban_plans WHERE id = %s", (int(plan_id),)
    ).fetchone()
    if plan is None:
        raise ValueError("找不到這個都市計畫")
    land_rows = conn.execute(
        "SELECT DISTINCT land_id FROM ownerships WHERE id = ANY(%s)",
        (_land_ids(ownership_ids),),
    ).fetchall()
    land_ids = _land_ids(row["land_id"] for row in land_rows)
    updated = []
    kept = []
    kept_total = 0
    if land_ids:
        updated = conn.execute(
            """
            UPDATE lands
            SET urban_plan_id = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = ANY(%s) AND urban_plan_id IS NULL
            RETURNING id
            """,
            (int(plan_id), land_ids),
        ).fetchall()
        kept = kept_lands(conn, land_ids, int(plan_id))
        kept_total = int(
            conn.execute(
                """
                SELECT COUNT(*)::integer AS count FROM lands
                WHERE id = ANY(%s) AND urban_plan_id IS NOT NULL
                  AND urban_plan_id <> %s
                """,
                (land_ids, int(plan_id)),
            ).fetchone()["count"]
        )
    audit_urban_plan(
        conn, user, "api_import_urban_plan", int(plan_id),
        f"Imported {len(land_ids)} lands into urban plan {plan['name']}",
    )
    return {
        "id": int(plan["id"]),
        "name": plan["name"],
        "assigned_land_count": len(updated),
        "kept_land_count": kept_total,
        "kept_lands": kept,
    }


class PostgreSQLUrbanPlanMixin:
    def list_urban_plans(self, user):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT plan.id, plan.name, plan.created_at,
                       (COUNT(DISTINCT land.id)
                            FILTER (WHERE ownership.id IS NOT NULL))::integer AS land_count,
                       COUNT(ownership.id)::integer AS ownership_count,
                       COUNT(DISTINCT ownership.owner_id)::integer AS owner_count
                FROM urban_plans plan
                LEFT JOIN lands land ON land.urban_plan_id = plan.id
                LEFT JOIN ownerships ownership ON ownership.land_id = land.id
                GROUP BY plan.id
                ORDER BY LOWER(plan.name), plan.id
                """
            ).fetchall()
            unassigned = conn.execute(
                """
                SELECT COUNT(DISTINCT land.id)::integer AS land_count,
                       COUNT(ownership.id)::integer AS ownership_count,
                       COUNT(DISTINCT ownership.owner_id)::integer AS owner_count
                FROM lands land
                JOIN ownerships ownership ON ownership.land_id = land.id
                WHERE land.urban_plan_id IS NULL
                """
            ).fetchone()
        return {
            "items": [{**_row_dict(row), "plan_id": int(row["id"])} for row in rows],
            "unassigned": _row_dict(unassigned),
        }

    def save_urban_plan(self, user, name, plan_id=None):
        name = " ".join(str(name or "").split())
        if not name:
            raise ValueError("都市計畫名稱不可空白")
        if len(name) > MAX_PLAN_NAME_LENGTH:
            raise ValueError(f"都市計畫名稱最多 {MAX_PLAN_NAME_LENGTH} 個字")
        if name == UNASSIGNED_LABEL:
            raise ValueError(f"「{UNASSIGNED_LABEL}」是系統保留名稱")
        with self._connect() as conn:
            duplicate = conn.execute(
                """
                SELECT id FROM urban_plans
                WHERE LOWER(name) = LOWER(%s)
                  AND (%s::bigint IS NULL OR id <> %s::bigint)
                """,
                (name, plan_id, plan_id),
            ).fetchone()
            if duplicate:
                raise ValueError("已有相同名稱的都市計畫")
            if plan_id is None:
                row = conn.execute(
                    "INSERT INTO urban_plans (name) VALUES (%s) RETURNING id",
                    (name,),
                ).fetchone()
                action_type = "api_create_urban_plan"
            else:
                row = conn.execute(
                    """
                    UPDATE urban_plans
                    SET name = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s RETURNING id
                    """,
                    (name, int(plan_id)),
                ).fetchone()
                if row is None:
                    raise KeyError(plan_id)
                action_type = "api_update_urban_plan"
            saved_id = int(row["id"])
            audit_urban_plan(
                conn, user, action_type, saved_id, f"Saved urban plan {name}"
            )
        return saved_id

    def delete_urban_plan(self, user, plan_id):
        """Delete a plan; its lands become 未分類. Returns None when it does not exist."""

        plan_id = int(plan_id)
        with self._connect() as conn:
            plan = conn.execute(
                "SELECT id, name FROM urban_plans WHERE id = %s", (plan_id,)
            ).fetchone()
            if plan is None:
                return None
            released = conn.execute(
                "SELECT COUNT(*)::integer AS count FROM lands WHERE urban_plan_id = %s",
                (plan_id,),
            ).fetchone()
            conn.execute("DELETE FROM urban_plans WHERE id = %s", (plan_id,))
            audit_urban_plan(
                conn, user, "api_delete_urban_plan", plan_id,
                f"Deleted urban plan {plan['name']}",
            )
        return {"deleted": True, "released_land_count": int(released["count"])}

    def set_lands_urban_plan(self, user, land_ids, plan_id, only_unassigned=True):
        """Assign lands to a plan (`plan_id` None/0 releases them to 未分類).

        With `only_unassigned` a land that already belongs to another plan is
        left alone and reported back in `kept_lands`.
        """

        land_ids = _land_ids(land_ids)
        target = int(plan_id) if plan_id not in (None, 0, "") else None
        if not land_ids:
            return {"updated_land_ids": [], "updated_count": 0, "kept_lands": []}
        with self._connect() as conn:
            found = conn.execute(
                "SELECT id FROM lands WHERE id = ANY(%s)", (land_ids,)
            ).fetchall()
            if len(found) != len(land_ids):
                raise KeyError("lands contain missing ids")
            plan_name = None
            if target is not None:
                plan = conn.execute(
                    "SELECT id, name FROM urban_plans WHERE id = %s", (target,)
                ).fetchone()
                if plan is None:
                    raise KeyError(target)
                plan_name = plan["name"]
            if target is None:
                updated = conn.execute(
                    """
                    UPDATE lands
                    SET urban_plan_id = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ANY(%s) AND urban_plan_id IS NOT NULL
                    RETURNING id
                    """,
                    (land_ids,),
                ).fetchall()
            elif only_unassigned:
                updated = conn.execute(
                    """
                    UPDATE lands
                    SET urban_plan_id = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ANY(%s) AND urban_plan_id IS NULL
                    RETURNING id
                    """,
                    (target, land_ids),
                ).fetchall()
            else:
                updated = conn.execute(
                    """
                    UPDATE lands
                    SET urban_plan_id = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ANY(%s) AND urban_plan_id IS DISTINCT FROM %s
                    RETURNING id
                    """,
                    (target, land_ids, target),
                ).fetchall()
            kept = []
            if target is not None and only_unassigned:
                kept = kept_lands(conn, land_ids, target)
            audit_urban_plan(
                conn, user, "api_set_lands_urban_plan", target or 0,
                f"Set urban plan {plan_name or 'none'} on {len(updated)} lands",
            )
        updated_ids = sorted(int(row["id"]) for row in updated)
        return {
            "updated_land_ids": updated_ids,
            "updated_count": len(updated_ids),
            "kept_lands": kept,
        }
