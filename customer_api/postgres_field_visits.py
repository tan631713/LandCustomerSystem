"""PostgreSQL repository operations for mobile field visits."""

from __future__ import annotations

import json

from customer_api.data_source_base import _decrypt_record, _row_dict
from customer_api.field_visit_service import (
    FieldVisitIdempotencyConflict,
    FieldVisitPlanConflict,
    FieldVisitTransitionError,
    validate_status_transition,
)


class PostgreSQLFieldVisitMixin:
    IDEMPOTENCY_TTL_HOURS = 24

    @staticmethod
    def _lock_idempotency_key(conn, user_id, idempotency_key):
        if idempotency_key is not None:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, %s))",
                (str(idempotency_key), int(user_id)),
            )

    @staticmethod
    def _cached_idempotency_result(
        conn, user_id, idempotency_key, request_hash
    ):
        if idempotency_key is None:
            return None
        conn.execute(
            """
            DELETE FROM field_visit_idempotency_keys
            WHERE user_id = %s AND idempotency_key = %s
              AND expires_at <= CURRENT_TIMESTAMP
            """,
            (int(user_id), str(idempotency_key)),
        )
        row = conn.execute(
            """
            SELECT request_hash, response_json, status_code
            FROM field_visit_idempotency_keys
            WHERE user_id = %s AND idempotency_key = %s
              AND expires_at > CURRENT_TIMESTAMP
            """,
            (int(user_id), str(idempotency_key)),
        ).fetchone()
        if row is None:
            return None
        if str(row["request_hash"]) != str(request_hash):
            raise FieldVisitIdempotencyConflict(
                "idempotency key was already used for a different request"
            )
        response = row["response_json"]
        return json.loads(response) if isinstance(response, str) else dict(response)

    def _save_idempotency_result(
        self,
        conn,
        user_id,
        idempotency_key,
        request_hash,
        response,
        status_code=200,
    ):
        if idempotency_key is None:
            return
        conn.execute(
            """
            INSERT INTO field_visit_idempotency_keys (
                user_id, idempotency_key, request_hash, response_json,
                status_code, expires_at
            ) VALUES (
                %s, %s, %s, %s::jsonb, %s,
                CURRENT_TIMESTAMP + (%s * INTERVAL '1 hour')
            )
            ON CONFLICT (user_id, idempotency_key) DO NOTHING
            """,
            (
                int(user_id),
                str(idempotency_key),
                str(request_hash),
                json.dumps(response, ensure_ascii=False),
                int(status_code),
                int(self.IDEMPOTENCY_TTL_HOURS),
            ),
        )

    @staticmethod
    def _route_access_row(conn, user, route_id, *, for_update=False):
        suffix = " FOR UPDATE" if for_update else ""
        row = conn.execute(
            """
            SELECT id, user_id, visit_date, title, status, start_latitude,
                   start_longitude, total_distance_km, started_at,
                   completed_at, created_at, updated_at
            FROM field_visit_routes
            WHERE id = %s
            """
            + suffix,
            (int(route_id),),
        ).fetchone()
        if row is None:
            raise KeyError(route_id)
        if user.role != "admin" and int(row["user_id"]) != int(user.id):
            raise PermissionError("field-visit route belongs to another user")
        return row

    @staticmethod
    def _require_field_visit_item_link(conn, user, record_id, item_id):
        row = conn.execute(
            """
            SELECT item.id, item.ownership_id, route.user_id
            FROM field_visit_route_items item
            JOIN field_visit_routes route ON route.id = item.route_id
            WHERE item.id = %s AND item.ownership_id = %s
            """,
            (int(item_id), int(record_id)),
        ).fetchone()
        if row is None:
            raise ValueError("行程項目與目前地主資料不一致。")
        if user.role != "admin" and int(row["user_id"]) != int(user.id):
            raise PermissionError("field-visit route belongs to another user")
        return int(row["id"])

    @staticmethod
    def _audit(conn, user, action_type, entity_type, entity_id, summary, detail=None):
        conn.execute(
            """
            INSERT INTO audit_logs (
                user_id, actor, action_type, entity_type, entity_id,
                summary, detail
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                user.id,
                user.username,
                str(action_type),
                str(entity_type),
                int(entity_id),
                str(summary),
                json.dumps(detail, ensure_ascii=False) if detail is not None else None,
            ),
        )

    def get_today_field_visit(self, user, visit_date):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM field_visit_routes
                WHERE visit_date = %s AND status <> 'cancelled'
                  AND (%s = 'admin' OR user_id = %s)
                ORDER BY id DESC
                LIMIT 1
                """,
                (visit_date, user.role, int(user.id)),
            ).fetchone()
            if row is None:
                return None
            return self._get_field_visit_route(conn, user, int(row["id"]))

    def get_field_visit_route(self, user, route_id):
        with self._connect() as conn:
            return self._get_field_visit_route(conn, user, int(route_id))

    @staticmethod
    def _candidate_rows(conn, route_id, *, for_update=False):
        lock_sql = " FOR UPDATE OF item" if for_update else ""
        return conn.execute(
            """
            SELECT item.id, item.status, item.priority, item.route_order,
                   item.is_order_locked, item.estimated_distance_km,
                   item.updated_at,
                   CASE WHEN location.geocode_status IN ('manual', 'success')
                        THEN location.latitude END AS latitude,
                   CASE WHEN location.geocode_status IN ('manual', 'success')
                        THEN location.longitude END AS longitude,
                   location.updated_at AS location_updated_at
            FROM field_visit_route_items item
            LEFT JOIN ownership_locations location
              ON location.ownership_id = item.ownership_id
            WHERE item.route_id = %s
            ORDER BY item.route_order, item.id
            """
            + lock_sql,
            (int(route_id),),
        ).fetchall()

    def get_field_visit_route_candidates(self, user, route_id):
        with self._connect() as conn:
            route = self._route_access_row(conn, user, route_id)
            items = self._candidate_rows(conn, route_id)
        result = _row_dict(route)
        result["items"] = [_row_dict(item) for item in items]
        return result

    def _get_field_visit_route(self, conn, user, route_id):
        route = self._route_access_row(conn, user, route_id)
        rows = conn.execute(
            """
            SELECT item.id, item.route_id, item.owner_id, item.ownership_id,
                   item.land_id, item.route_order, item.status, item.priority,
                   item.is_order_locked, item.estimated_distance_km,
                   item.arrived_at, item.completed_at, item.postponed_until,
                   item.note, item.created_at, item.updated_at,
                   land.district, land.section, land.land_number,
                   ownership.registration_order,
                   COALESCE(ownership.owner_name_override, owner.owner_name) AS owner_name,
                   COALESCE(ownership.external_id_override, owner.external_id) AS external_id,
                   COALESCE(ownership.address_override, owner.address) AS address,
                   owner.phone,
                   CASE WHEN location.geocode_status IN ('manual', 'success')
                        THEN location.latitude END AS latitude,
                   CASE WHEN location.geocode_status IN ('manual', 'success')
                        THEN location.longitude END AS longitude,
                   location.geocode_status, location.geocode_source,
                   (
                       SELECT CONCAT_WS('｜', NULLIF(log.method, ''), NULLIF(log.result, ''))
                       FROM contact_logs log
                       WHERE log.ownership_id = ownership.id
                       ORDER BY COALESCE(log.contacted_at, log.created_at) DESC, log.id DESC
                       LIMIT 1
                   ) AS last_contact,
                   (
                       SELECT COUNT(*)::integer
                       FROM contact_logs log
                       WHERE log.ownership_id = ownership.id
                   ) AS contact_log_count,
                   (
                       SELECT COUNT(*)::integer
                       FROM attachments attachment
                       WHERE attachment.ownership_id = ownership.id
                   ) AS attachment_count
            FROM field_visit_route_items item
            JOIN ownerships ownership ON ownership.id = item.ownership_id
            JOIN owners owner ON owner.id = item.owner_id
            JOIN lands land ON land.id = item.land_id
            LEFT JOIN ownership_locations location
              ON location.ownership_id = item.ownership_id
            WHERE item.route_id = %s
            ORDER BY item.route_order, item.id
            """,
            (int(route_id),),
        ).fetchall()
        result = _row_dict(route)
        result["items"] = [_decrypt_record(row, user) for row in rows]
        return result

    def create_field_visit_route(
        self,
        user,
        values,
        *,
        idempotency_key=None,
        request_hash="",
    ):
        with self._connect() as conn:
            self._lock_idempotency_key(conn, user.id, idempotency_key)
            cached = self._cached_idempotency_result(
                conn, user.id, idempotency_key, request_hash
            )
            if cached is not None:
                return cached
            row = conn.execute(
                """
                INSERT INTO field_visit_routes (
                    visit_date, user_id, title, status,
                    start_latitude, start_longitude
                ) VALUES (%s, %s, %s, 'planned', %s, %s)
                ON CONFLICT (user_id, visit_date)
                    WHERE status <> 'cancelled'
                DO NOTHING
                RETURNING id, user_id, visit_date, title, status,
                          start_latitude, start_longitude, total_distance_km,
                          started_at, completed_at, created_at, updated_at
                """,
                (
                    values["visit_date"],
                    int(user.id),
                    values.get("title") or "",
                    values.get("start_latitude"),
                    values.get("start_longitude"),
                ),
            ).fetchone()
            created = row is not None
            if row is None:
                row = conn.execute(
                    """
                    SELECT id, user_id, visit_date, title, status,
                           start_latitude, start_longitude, total_distance_km,
                           started_at, completed_at, created_at, updated_at
                    FROM field_visit_routes
                    WHERE user_id = %s AND visit_date = %s
                      AND status <> 'cancelled'
                    """,
                    (int(user.id), values["visit_date"]),
                ).fetchone()
            response = _row_dict(row)
            response["created"] = created
            if created:
                self._audit(
                    conn,
                    user,
                    "api_create_field_visit_route",
                    "field_visit_route",
                    row["id"],
                    f"Created field-visit route for {row['visit_date']}",
                )
            self._save_idempotency_result(
                conn,
                user.id,
                idempotency_key,
                request_hash,
                response,
                status_code=201 if created else 200,
            )
        return response

    def add_field_visit_items(
        self,
        user,
        route_id,
        items,
        *,
        idempotency_key=None,
        request_hash="",
    ):
        route_id = int(route_id)
        with self._connect() as conn:
            self._lock_idempotency_key(conn, user.id, idempotency_key)
            cached = self._cached_idempotency_result(
                conn, user.id, idempotency_key, request_hash
            )
            if cached is not None:
                return cached
            route = self._route_access_row(conn, user, route_id, for_update=True)
            if route["status"] in {"completed", "cancelled"}:
                raise ValueError("completed or cancelled routes cannot accept items")
            ownership_ids = [int(item["ownership_id"]) for item in items]
            ownership_rows = conn.execute(
                """
                SELECT id, owner_id, land_id
                FROM ownerships
                WHERE id = ANY(%s)
                """,
                (ownership_ids,),
            ).fetchall()
            ownership_by_id = {
                int(row["id"]): row for row in ownership_rows
            }
            if len(ownership_by_id) != len(ownership_ids):
                raise KeyError("one or more ownerships do not exist")
            existing_rows = conn.execute(
                """
                SELECT ownership_id, route_order
                FROM field_visit_route_items
                WHERE route_id = %s
                """,
                (route_id,),
            ).fetchall()
            existing_ids = {int(row["ownership_id"]) for row in existing_rows}
            used_orders = {int(row["route_order"]) for row in existing_rows}
            next_order = max(used_orders, default=0) + 1
            added_ids = []
            for item in items:
                ownership_id = int(item["ownership_id"])
                if ownership_id in existing_ids:
                    continue
                requested_order = item.get("route_order")
                if requested_order is None:
                    while next_order in used_orders:
                        next_order += 1
                    route_order = next_order
                    next_order += 1
                else:
                    route_order = int(requested_order)
                    if route_order in used_orders:
                        raise ValueError(f"route_order {route_order} is already in use")
                ownership = ownership_by_id[ownership_id]
                row = conn.execute(
                    """
                    INSERT INTO field_visit_route_items (
                        route_id, owner_id, ownership_id, land_id,
                        route_order, status, priority, is_order_locked, note
                    ) VALUES (%s, %s, %s, %s, %s, 'planned', %s, %s, %s)
                    ON CONFLICT (route_id, ownership_id) DO NOTHING
                    RETURNING id
                    """,
                    (
                        route_id,
                        int(ownership["owner_id"]),
                        ownership_id,
                        int(ownership["land_id"]),
                        route_order,
                        int(item.get("priority") or 0),
                        bool(item.get("is_order_locked")),
                        str(item.get("note") or "") or None,
                    ),
                ).fetchone()
                if row is not None:
                    added_ids.append(int(row["id"]))
                    existing_ids.add(ownership_id)
                    used_orders.add(route_order)
            conn.execute(
                """
                UPDATE field_visit_routes
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (route_id,),
            )
            response = {
                "route_id": route_id,
                "added_count": len(added_ids),
                "existing_count": len(items) - len(added_ids),
                "item_ids": added_ids,
            }
            if added_ids:
                self._audit(
                    conn,
                    user,
                    "api_add_field_visit_items",
                    "field_visit_route",
                    route_id,
                    f"Added {len(added_ids)} items to field-visit route",
                    {"item_ids": added_ids, "ownership_ids": ownership_ids},
                )
            self._save_idempotency_result(
                conn,
                user.id,
                idempotency_key,
                request_hash,
                response,
                status_code=201,
            )
        return response

    def transition_field_visit_item(
        self,
        user,
        item_id,
        new_status,
        *,
        latitude=None,
        longitude=None,
        note="",
        postponed_until=None,
        allowed_old_statuses=None,
        idempotency_key=None,
        request_hash="",
    ):
        item_id = int(item_id)
        with self._connect() as conn:
            self._lock_idempotency_key(conn, user.id, idempotency_key)
            cached = self._cached_idempotency_result(
                conn, user.id, idempotency_key, request_hash
            )
            if cached is not None:
                return cached
            current = conn.execute(
                """
                SELECT item.id, item.route_id, item.status, route.user_id
                FROM field_visit_route_items item
                JOIN field_visit_routes route ON route.id = item.route_id
                WHERE item.id = %s
                FOR UPDATE OF item, route
                """,
                (item_id,),
            ).fetchone()
            if current is None:
                raise KeyError(item_id)
            if user.role != "admin" and int(current["user_id"]) != int(user.id):
                raise PermissionError("field-visit item belongs to another user")
            old_status = str(current["status"])
            if (
                allowed_old_statuses is not None
                and old_status not in set(allowed_old_statuses)
            ):
                raise FieldVisitTransitionError(
                    "only field-visit items that have not started can be removed"
                )
            validate_status_transition(old_status, new_status)
            if old_status == new_status:
                response = {
                    "item_id": item_id,
                    "route_id": int(current["route_id"]),
                    "old_status": old_status,
                    "new_status": new_status,
                    "changed": False,
                }
                self._save_idempotency_result(
                    conn,
                    user.id,
                    idempotency_key,
                    request_hash,
                    response,
                )
                return response
            updated = conn.execute(
                """
                UPDATE field_visit_route_items
                SET status = %s,
                    arrived_at = CASE
                        WHEN %s = 'in_progress'
                        THEN COALESCE(arrived_at, CURRENT_TIMESTAMP)
                        ELSE arrived_at
                    END,
                    completed_at = CASE
                        WHEN %s = 'completed' THEN CURRENT_TIMESTAMP
                        ELSE completed_at
                    END,
                    postponed_until = %s::timestamptz,
                    note = CASE WHEN %s <> '' THEN %s ELSE note END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, route_id, status, arrived_at,
                          completed_at, postponed_until, updated_at
                """,
                (
                    new_status,
                    new_status,
                    new_status,
                    postponed_until,
                    str(note or ""),
                    str(note or ""),
                    item_id,
                ),
            ).fetchone()
            history = conn.execute(
                """
                INSERT INTO field_visit_status_history (
                    route_item_id, old_status, new_status, user_id,
                    latitude, longitude, note
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    item_id,
                    old_status,
                    new_status,
                    user.id,
                    latitude,
                    longitude,
                    str(note or "") or None,
                ),
            ).fetchone()
            route_id = int(updated["route_id"])
            conn.execute(
                """
                UPDATE field_visit_routes
                SET status = CASE
                        WHEN %s IN ('planned', 'in_progress', 'postponed')
                             AND status = 'completed'
                        THEN 'in_progress'
                        WHEN status IN ('draft', 'planned') THEN 'in_progress'
                        ELSE status
                    END,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    completed_at = CASE
                        WHEN %s IN ('planned', 'in_progress', 'postponed')
                        THEN NULL
                        ELSE completed_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (new_status, new_status, route_id),
            )
            remaining = conn.execute(
                """
                SELECT COUNT(*)::integer AS remaining
                FROM field_visit_route_items
                WHERE route_id = %s
                  AND status IN ('planned', 'in_progress', 'postponed')
                """,
                (route_id,),
            ).fetchone()
            if int(remaining["remaining"]) == 0:
                conn.execute(
                    """
                    UPDATE field_visit_routes
                    SET status = 'completed',
                        completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (route_id,),
                )
            self._audit(
                conn,
                user,
                "api_transition_field_visit_item",
                "field_visit_route_item",
                item_id,
                f"Changed field-visit item from {old_status} to {new_status}",
                {
                    "route_id": route_id,
                    "old_status": old_status,
                    "new_status": new_status,
                    "history_id": int(history["id"]),
                },
            )
            response = {
                "item_id": item_id,
                "route_id": route_id,
                "old_status": old_status,
                "new_status": new_status,
                "changed": True,
                "history_id": int(history["id"]),
            }
            self._save_idempotency_result(
                conn,
                user.id,
                idempotency_key,
                request_hash,
                response,
            )
        return response

    def update_field_visit_item(
        self,
        user,
        item_id,
        *,
        priority=None,
        is_order_locked=None,
        idempotency_key=None,
        request_hash="",
    ):
        item_id = int(item_id)
        with self._connect() as conn:
            self._lock_idempotency_key(conn, user.id, idempotency_key)
            cached = self._cached_idempotency_result(
                conn, user.id, idempotency_key, request_hash
            )
            if cached is not None:
                return cached
            current = conn.execute(
                """
                SELECT item.id, item.route_id, item.status, item.priority,
                       item.is_order_locked, route.user_id
                FROM field_visit_route_items item
                JOIN field_visit_routes route ON route.id = item.route_id
                WHERE item.id = %s
                FOR UPDATE OF item, route
                """,
                (item_id,),
            ).fetchone()
            if current is None:
                raise KeyError(item_id)
            if user.role != "admin" and int(current["user_id"]) != int(user.id):
                raise PermissionError("field-visit item belongs to another user")
            if str(current["status"]) not in {"planned", "postponed"}:
                raise FieldVisitTransitionError(
                    "only pending field-visit items can change priority"
                )
            new_priority = (
                int(current["priority"]) if priority is None else int(priority)
            )
            new_locked = (
                bool(current["is_order_locked"])
                if is_order_locked is None
                else bool(is_order_locked)
            )
            changed = (
                new_priority != int(current["priority"])
                or new_locked != bool(current["is_order_locked"])
            )
            if changed:
                conn.execute(
                    """
                    UPDATE field_visit_route_items
                    SET priority = %s,
                        is_order_locked = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (new_priority, new_locked, item_id),
                )
                self._audit(
                    conn,
                    user,
                    "api_update_field_visit_item",
                    "field_visit_route_item",
                    item_id,
                    "Updated field-visit item priority settings",
                    {
                        "route_id": int(current["route_id"]),
                        "old_priority": int(current["priority"]),
                        "new_priority": new_priority,
                        "old_is_order_locked": bool(current["is_order_locked"]),
                        "new_is_order_locked": new_locked,
                    },
                )
            response = {
                "item_id": item_id,
                "route_id": int(current["route_id"]),
                "priority": new_priority,
                "is_order_locked": new_locked,
                "changed": changed,
            }
            self._save_idempotency_result(
                conn,
                user.id,
                idempotency_key,
                request_hash,
                response,
            )
        return response

    @staticmethod
    def _candidate_signature(items):
        fields = (
            "id",
            "status",
            "priority",
            "route_order",
            "is_order_locked",
            "latitude",
            "longitude",
            "updated_at",
            "location_updated_at",
        )
        return [
            {field: item.get(field) for field in fields}
            for item in sorted(items, key=lambda value: int(value["id"]))
        ]

    def apply_field_visit_route_order(
        self,
        user,
        route_id,
        plan_items,
        *,
        expected_items,
        start_latitude=None,
        start_longitude=None,
        total_distance_km=None,
        idempotency_key=None,
        request_hash="",
        action_type="api_optimize_field_visit_route",
    ):
        route_id = int(route_id)
        with self._connect() as conn:
            self._lock_idempotency_key(conn, user.id, idempotency_key)
            cached = self._cached_idempotency_result(
                conn, user.id, idempotency_key, request_hash
            )
            if cached is not None:
                return cached
            self._route_access_row(conn, user, route_id, for_update=True)
            current_rows = [
                _row_dict(row)
                for row in self._candidate_rows(conn, route_id, for_update=True)
            ]
            if self._candidate_signature(current_rows) != self._candidate_signature(
                expected_items
            ):
                raise FieldVisitPlanConflict(
                    "field-visit route changed before the plan was applied"
                )
            eligible_statuses = {"planned", "in_progress", "postponed"}
            eligible = [
                item
                for item in current_rows
                if str(item.get("status")) in eligible_statuses
            ]
            eligible_ids = {int(item["id"]) for item in eligible}
            plan_ids = [int(item["item_id"]) for item in plan_items]
            plan_orders = [int(item["route_order"]) for item in plan_items]
            if len(plan_ids) != len(set(plan_ids)) or set(plan_ids) != eligible_ids:
                raise FieldVisitPlanConflict(
                    "route plan does not contain every remaining item exactly once"
                )
            active_orders = {int(item["route_order"]) for item in eligible}
            if set(plan_orders) != active_orders or len(plan_orders) != len(
                set(plan_orders)
            ):
                raise FieldVisitPlanConflict(
                    "route plan would overwrite a completed or excluded item"
                )
            by_id = {int(item["id"]): item for item in eligible}
            if action_type == "api_optimize_field_visit_route":
                for item in plan_items:
                    current = by_id[int(item["item_id"])]
                    if current.get("is_order_locked") and int(
                        item["route_order"]
                    ) != int(current["route_order"]):
                        raise FieldVisitPlanConflict(
                            "automatic optimization cannot move a locked item"
                        )
            conn.execute(
                "SET CONSTRAINTS uq_field_visit_route_items_order DEFERRED"
            )
            for item in plan_items:
                lock_value = item.get("is_order_locked")
                conn.execute(
                    """
                    UPDATE field_visit_route_items
                    SET route_order = %s,
                        estimated_distance_km = %s,
                        is_order_locked = COALESCE(%s, is_order_locked),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND route_id = %s
                    """,
                    (
                        int(item["route_order"]),
                        item.get("estimated_distance_km"),
                        lock_value,
                        int(item["item_id"]),
                        route_id,
                    ),
                )
            conn.execute(
                """
                UPDATE field_visit_routes
                SET start_latitude = %s,
                    start_longitude = %s,
                    total_distance_km = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    start_latitude,
                    start_longitude,
                    total_distance_km,
                    route_id,
                ),
            )
            response = {
                "route_id": route_id,
                "applied": True,
                "updated_count": len(plan_items),
                "items": [
                    {
                        "item_id": int(item["item_id"]),
                        "route_order": int(item["route_order"]),
                        "estimated_distance_km": item.get(
                            "estimated_distance_km"
                        ),
                    }
                    for item in plan_items
                ],
            }
            self._audit(
                conn,
                user,
                action_type,
                "field_visit_route",
                route_id,
                f"Applied order to {len(plan_items)} field-visit items",
                {"items": response["items"]},
            )
            self._save_idempotency_result(
                conn,
                user.id,
                idempotency_key,
                request_hash,
                response,
            )
        return response
