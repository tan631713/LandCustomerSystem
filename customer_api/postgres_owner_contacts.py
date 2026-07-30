"""PostgreSQL repositories and transactions for owner related people."""

from __future__ import annotations

import json
import re

from customer_api.owner_contact_service import (
    OwnerContactConcurrentUpdate,
    OwnerContactConflict,
    OwnerContactNotFound,
    OwnerContactService,
)


def _dict(row):
    if row is None:
        return None
    result = dict(row)
    for key, value in tuple(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def normalize_phone(value):
    return re.sub(r"[^0-9A-Za-z]", "", str(value or "")).casefold()


def _same_text(left, right):
    return str(left or "").strip().casefold() == str(right or "").strip().casefold()


class ContactRepository:
    def __init__(self, conn):
        self.conn = conn

    def create(self, values):
        row = self.conn.execute(
            """
            INSERT INTO contacts (
                name, mobile_phone, home_phone, registered_address,
                contact_address, work_address, identity_note, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                values["name"],
                values["mobile_phone"] or None,
                values["home_phone"] or None,
                values["registered_address"] or None,
                values["contact_address"] or None,
                values["work_address"] or None,
                values["identity_note"] or None,
                values["notes"] or None,
            ),
        ).fetchone()
        return int(row["id"])

    def get(self, contact_id):
        return _dict(
            self.conn.execute(
                """
                SELECT id, name, mobile_phone, home_phone,
                       registered_address, contact_address, work_address,
                       identity_note, notes, is_active, created_at, updated_at
                FROM contacts WHERE id = %s
                """,
                (int(contact_id),),
            ).fetchone()
        )

    def require_active(self, contact_id):
        row = self.get(contact_id)
        if row is None:
            raise OwnerContactNotFound("關係人不存在。")
        if not row["is_active"]:
            raise OwnerContactConflict("關係人目前已停用。")
        return row

    def update(self, contact_id, values, *, expected_updated_at=None):
        parameters = [
            values["name"],
            values["mobile_phone"] or None,
            values["home_phone"] or None,
            values["registered_address"] or None,
            values["contact_address"] or None,
            values["work_address"] or None,
            values["identity_note"] or None,
            values["notes"] or None,
            int(contact_id),
        ]
        expected_clause = ""
        if expected_updated_at:
            expected_clause = " AND updated_at = %s::timestamptz"
            parameters.append(str(expected_updated_at))
        row = self.conn.execute(
            f"""
            UPDATE contacts SET
                name = %s, mobile_phone = %s, home_phone = %s,
                registered_address = %s, contact_address = %s,
                work_address = %s, identity_note = %s, notes = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s{expected_clause}
            RETURNING id
            """,
            tuple(parameters),
        ).fetchone()
        if row is None:
            if self.get(contact_id) is None:
                raise OwnerContactNotFound("關係人不存在。")
            raise OwnerContactConcurrentUpdate(
                "關係人資料已被其他使用者修改，請重新整理後再編輯。"
            )

    def search(self, query, limit=50):
        query = str(query or "").strip()
        if not query:
            return []
        pattern = f"%{query}%"
        phone_query = normalize_phone(query)
        phone_pattern = f"%{phone_query}%"
        rows = self.conn.execute(
            """
            SELECT contact.id, contact.name, contact.mobile_phone,
                   contact.home_phone, contact.registered_address,
                   contact.contact_address, contact.work_address,
                   contact.identity_note, contact.notes,
                   contact.is_active, contact.created_at, contact.updated_at,
                   COUNT(DISTINCT relation.owner_id)
                       FILTER (WHERE relation.is_active) AS owner_count
            FROM contacts contact
            LEFT JOIN owner_contact_relations relation
                   ON relation.contact_id = contact.id
            WHERE contact.is_active
              AND (
                  contact.name ILIKE %s
                  OR COALESCE(contact.registered_address, '') ILIKE %s
                  OR COALESCE(contact.contact_address, '') ILIKE %s
                  OR (
                      %s <> ''
                      AND REGEXP_REPLACE(
                          COALESCE(contact.mobile_phone, ''),
                          '[^0-9A-Za-z]', '', 'g'
                      ) ILIKE %s
                  )
                  OR (
                      %s <> ''
                      AND REGEXP_REPLACE(
                          COALESCE(contact.home_phone, ''),
                          '[^0-9A-Za-z]', '', 'g'
                      ) ILIKE %s
                  )
              )
            GROUP BY contact.id
            ORDER BY contact.name, contact.id
            LIMIT %s
            """,
            (
                pattern,
                pattern,
                pattern,
                phone_query,
                phone_pattern,
                phone_query,
                phone_pattern,
                max(1, min(int(limit), 50)),
            ),
        ).fetchall()
        return [_dict(row) for row in rows]

    def possible_duplicates(
        self,
        name="",
        mobile_phone="",
        home_phone="",
        registered_address="",
        contact_address="",
        limit=20,
    ):
        name = str(name or "").strip()
        mobile_normalized = normalize_phone(mobile_phone)
        home_normalized = normalize_phone(home_phone)
        registered_address = str(registered_address or "").strip()
        contact_address = str(contact_address or "").strip()
        if not name and not mobile_normalized and not home_normalized:
            return []
        rows = self.conn.execute(
            """
            SELECT contact.id, contact.name, contact.mobile_phone,
                   contact.home_phone, contact.registered_address,
                   contact.contact_address, contact.work_address,
                   contact.identity_note, contact.notes,
                   contact.is_active, contact.created_at, contact.updated_at,
                   COUNT(DISTINCT relation.owner_id)
                       FILTER (WHERE relation.is_active) AS owner_count
            FROM contacts contact
            LEFT JOIN owner_contact_relations relation
                   ON relation.contact_id = contact.id
            WHERE contact.is_active
              AND (
                  (
                      %s <> ''
                      AND REGEXP_REPLACE(
                          COALESCE(contact.mobile_phone, ''),
                          '[^0-9A-Za-z]', '', 'g'
                      ) = %s
                  )
                  OR (
                      %s <> ''
                      AND REGEXP_REPLACE(
                          COALESCE(contact.home_phone, ''),
                          '[^0-9A-Za-z]', '', 'g'
                      ) = %s
                  )
                  OR (%s <> '' AND contact.name = %s)
              )
            GROUP BY contact.id
            ORDER BY contact.name, contact.id
            LIMIT %s
            """,
            (
                mobile_normalized,
                mobile_normalized,
                home_normalized,
                home_normalized,
                name,
                name,
                max(1, min(int(limit), 50)),
            ),
        ).fetchall()
        matches = []
        for raw_row in rows:
            row = _dict(raw_row)
            reasons = []
            if (
                mobile_normalized
                and normalize_phone(row.get("mobile_phone")) == mobile_normalized
            ):
                reasons.append("手機相同")
            if (
                home_normalized
                and normalize_phone(row.get("home_phone")) == home_normalized
            ):
                reasons.append("市話相同")
            same_name = bool(name and _same_text(row.get("name"), name))
            if (
                same_name
                and contact_address
                and _same_text(row.get("contact_address"), contact_address)
            ):
                reasons.append("姓名及聯絡地址相同")
            if (
                same_name
                and registered_address
                and _same_text(row.get("registered_address"), registered_address)
            ):
                reasons.append("姓名及戶籍地址相同")
            strength = "high" if reasons else ("possible" if same_name else "")
            if not strength:
                continue
            row["duplicate_strength"] = strength
            row["duplicate_reasons"] = reasons or ["姓名相同"]
            matches.append(row)
        matches.sort(
            key=lambda item: (
                item.get("duplicate_strength") != "high",
                str(item.get("name") or ""),
                int(item.get("id") or 0),
            )
        )
        return matches


class OwnerContactRelationRepository:
    VIEW_SELECT = """
        SELECT relation.id AS relation_id, relation.owner_id,
               relation.contact_id, contact.name, relation.relationship_type,
               relation.relationship_note, contact.mobile_phone,
               contact.home_phone, contact.registered_address,
               contact.contact_address, contact.work_address,
               contact.identity_note, relation.is_primary,
               relation.sort_order, contact.notes AS contact_notes,
               relation.notes AS relation_notes, relation.is_active,
               contact.is_active AS contact_is_active,
               relation.deactivated_at, relation.deactivated_by,
               relation.created_at, relation.updated_at,
               relation.updated_at AS relation_updated_at,
               contact.updated_at AS contact_updated_at,
               (
                   SELECT COUNT(DISTINCT linked.owner_id)
                   FROM owner_contact_relations linked
                   WHERE linked.contact_id = contact.id AND linked.is_active
               ) AS owner_count
        FROM owner_contact_relations relation
        JOIN contacts contact ON contact.id = relation.contact_id
    """

    def __init__(self, conn):
        self.conn = conn

    def require_owner(self, owner_id):
        row = self.conn.execute(
            "SELECT id FROM owners WHERE id = %s", (int(owner_id),)
        ).fetchone()
        if row is None:
            raise OwnerContactNotFound("地主不存在。")

    def list(self, owner_id, include_inactive=False):
        rows = self.conn.execute(
            self.VIEW_SELECT
            + """
              WHERE relation.owner_id = %s
                AND (%s OR relation.is_active)
              ORDER BY relation.is_primary DESC,
                       relation.sort_order ASC, contact.name ASC, relation.id ASC
            """,
            (int(owner_id), bool(include_inactive)),
        ).fetchall()
        return [_dict(row) for row in rows]

    def get(self, owner_id, relation_id):
        return _dict(
            self.conn.execute(
                self.VIEW_SELECT
                + " WHERE relation.owner_id = %s AND relation.id = %s",
                (int(owner_id), int(relation_id)),
            ).fetchone()
        )

    def exists(
        self,
        owner_id,
        contact_id,
        *,
        active_only=True,
        excluding_relation_id=None,
    ):
        clauses = ["owner_id = %s", "contact_id = %s"]
        parameters = [int(owner_id), int(contact_id)]
        if active_only:
            clauses.append("is_active")
        if excluding_relation_id is not None:
            clauses.append("id <> %s")
            parameters.append(int(excluding_relation_id))
        row = self.conn.execute(
            f"SELECT 1 FROM owner_contact_relations WHERE {' AND '.join(clauses)} LIMIT 1",
            tuple(parameters),
        ).fetchone()
        return row is not None

    def create(self, owner_id, contact_id, values):
        if self.exists(owner_id, contact_id, active_only=True):
            raise OwnerContactConflict("該關係人已連結此地主。")
        row = self.conn.execute(
            """
            INSERT INTO owner_contact_relations (
                owner_id, contact_id, relationship_type, relationship_note,
                is_primary, sort_order, notes
            ) VALUES (%s, %s, %s, %s, FALSE, %s, %s)
            RETURNING id
            """,
            (
                int(owner_id),
                int(contact_id),
                values["relationship_type"],
                values["relationship_note"] or None,
                int(values["sort_order"]),
                values["notes"] or None,
            ),
        ).fetchone()
        return int(row["id"])

    def update(
        self,
        owner_id,
        relation_id,
        values,
        *,
        expected_updated_at=None,
    ):
        parameters = [
            values["relationship_type"],
            values["relationship_note"] or None,
            int(values["sort_order"]),
            values["notes"] or None,
            int(owner_id),
            int(relation_id),
        ]
        expected_clause = ""
        if expected_updated_at:
            expected_clause = " AND updated_at = %s::timestamptz"
            parameters.append(str(expected_updated_at))
        row = self.conn.execute(
            f"""
            UPDATE owner_contact_relations SET
                relationship_type = %s, relationship_note = %s,
                is_primary = FALSE, sort_order = %s, notes = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE owner_id = %s AND id = %s AND is_active{expected_clause}
            RETURNING id
            """,
            tuple(parameters),
        ).fetchone()
        if row is None:
            current = self.get(owner_id, relation_id)
            if current is None:
                raise OwnerContactNotFound("關係不存在。")
            if not current["is_active"]:
                raise OwnerContactConflict("關係已停用。")
            raise OwnerContactConcurrentUpdate(
                "地主關係已被其他使用者修改，請重新整理後再編輯。"
            )

    def set_primary(self, owner_id, relation_id):
        target = self.get(owner_id, relation_id)
        if target is None:
            raise OwnerContactNotFound("關係不存在。")
        if not target["is_active"]:
            raise OwnerContactConflict("關係已停用。")
        previous = [
            _dict(row)
            for row in self.conn.execute(
                self.VIEW_SELECT
                + """
                  WHERE relation.owner_id = %s
                    AND relation.is_active
                    AND relation.is_primary
                    AND relation.id <> %s
                """,
                (int(owner_id), int(relation_id)),
            ).fetchall()
        ]
        self.conn.execute(
            """
            UPDATE owner_contact_relations
            SET is_primary = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE owner_id = %s AND is_active AND is_primary AND id <> %s
            """,
            (int(owner_id), int(relation_id)),
        )
        self.conn.execute(
            """
            UPDATE owner_contact_relations
            SET is_primary = TRUE, updated_at = CURRENT_TIMESTAMP
            WHERE owner_id = %s AND id = %s AND is_active
            """,
            (int(owner_id), int(relation_id)),
        )
        return previous

    def deactivate(
        self,
        owner_id,
        relation_id,
        *,
        actor_id,
        expected_updated_at=None,
    ):
        parameters = [int(actor_id), int(owner_id), int(relation_id)]
        expected_clause = ""
        if expected_updated_at:
            expected_clause = " AND updated_at = %s::timestamptz"
            parameters.append(str(expected_updated_at))
        row = self.conn.execute(
            f"""
            UPDATE owner_contact_relations
            SET is_active = FALSE, is_primary = FALSE,
                deactivated_at = CURRENT_TIMESTAMP, deactivated_by = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE owner_id = %s AND id = %s AND is_active{expected_clause}
            RETURNING id
            """,
            tuple(parameters),
        ).fetchone()
        if row is None:
            current = self.get(owner_id, relation_id)
            if current is None:
                raise OwnerContactNotFound("關係不存在。")
            if not current["is_active"]:
                raise OwnerContactConflict("關係已停用。")
            raise OwnerContactConcurrentUpdate(
                "地主關係已被其他使用者修改，請重新整理後再停用。"
            )

    def reactivate(self, owner_id, relation_id, *, expected_updated_at=None):
        parameters = [int(owner_id), int(relation_id)]
        expected_clause = ""
        if expected_updated_at:
            expected_clause = " AND updated_at = %s::timestamptz"
            parameters.append(str(expected_updated_at))
        row = self.conn.execute(
            f"""
            UPDATE owner_contact_relations
            SET is_active = TRUE, is_primary = FALSE,
                deactivated_at = NULL, deactivated_by = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE owner_id = %s AND id = %s AND NOT is_active{expected_clause}
            RETURNING id
            """,
            tuple(parameters),
        ).fetchone()
        if row is None:
            current = self.get(owner_id, relation_id)
            if current is None:
                raise OwnerContactNotFound("關係不存在。")
            if current["is_active"]:
                raise OwnerContactConflict("關係已啟用。")
            raise OwnerContactConcurrentUpdate(
                "地主關係已被其他使用者修改，請重新整理後再啟用。"
            )


class PostgreSQLOwnerContactMixin:
    @staticmethod
    def _owner_id_for_record(conn, record_id):
        row = conn.execute(
            "SELECT owner_id FROM ownerships WHERE id = %s", (int(record_id),)
        ).fetchone()
        if row is None:
            raise OwnerContactNotFound("地主不存在。")
        return int(row["owner_id"])

    @staticmethod
    def _owner_contact_audit(
        conn,
        actor,
        action_type,
        owner_id,
        contact_id,
        relation_id,
        before,
        after,
    ):
        conn.execute(
            """
            INSERT INTO audit_logs (
                user_id, actor, action_type, entity_type, entity_id,
                summary, detail
            ) VALUES (%s, %s, %s, 'owner_contact_relation', %s, %s, %s::jsonb)
            """,
            (
                int(actor.id),
                actor.username,
                action_type,
                int(relation_id),
                f"地主 {int(owner_id)}／關係人 {int(contact_id)}",
                json.dumps(
                    {
                        "owner_id": int(owner_id),
                        "contact_id": int(contact_id),
                        "relation_id": int(relation_id),
                        "before": before,
                        "after": after,
                    },
                    ensure_ascii=False,
                ),
            ),
        )

    def _owner_contact_service(self, conn):
        return OwnerContactService(
            ContactRepository(conn),
            OwnerContactRelationRepository(conn),
            lambda actor, action, owner_id, contact_id, relation_id, before, after:
                self._owner_contact_audit(
                    conn,
                    actor,
                    action,
                    owner_id,
                    contact_id,
                    relation_id,
                    before,
                    after,
                ),
        )

    def list_owner_contacts(self, user, record_id, include_inactive=False):
        with self._connect() as conn:
            owner_id = self._owner_id_for_record(conn, record_id)
            items = OwnerContactRelationRepository(conn).list(
                owner_id, include_inactive=include_inactive
            )
        return {"owner_id": owner_id, "items": items}

    def get_owner_contact_relation(self, user, record_id, relation_id):
        with self._connect() as conn:
            owner_id = self._owner_id_for_record(conn, record_id)
            item = OwnerContactRelationRepository(conn).get(owner_id, relation_id)
        if item is None:
            raise OwnerContactNotFound("關係不存在。")
        return item

    def list_owner_contacts_by_owner(
        self, user, owner_id, include_inactive=False
    ):
        with self._connect() as conn:
            relations = OwnerContactRelationRepository(conn)
            relations.require_owner(owner_id)
            items = relations.list(
                owner_id, include_inactive=include_inactive
            )
        return {"owner_id": int(owner_id), "items": items}

    def get_owner_contact_relation_by_owner(
        self, user, owner_id, relation_id
    ):
        with self._connect() as conn:
            relations = OwnerContactRelationRepository(conn)
            relations.require_owner(owner_id)
            item = relations.get(owner_id, relation_id)
        if item is None:
            raise OwnerContactNotFound("關係不存在。")
        return item

    def search_owner_contacts(self, user, query, limit=50):
        with self._connect() as conn:
            return ContactRepository(conn).search(query, limit=limit)

    def find_owner_contact_duplicates(
        self,
        user,
        name="",
        mobile_phone="",
        home_phone="",
        registered_address="",
        contact_address="",
        limit=20,
    ):
        with self._connect() as conn:
            return ContactRepository(conn).possible_duplicates(
                name=name,
                mobile_phone=mobile_phone,
                home_phone=home_phone,
                registered_address=registered_address,
                contact_address=contact_address,
                limit=limit,
            )

    def create_owner_contact(self, user, record_id, values):
        try:
            with self._connect() as conn:
                owner_id = self._owner_id_for_record(conn, record_id)
                return self._owner_contact_service(conn).create_new(
                    owner_id,
                    user,
                    values["contact"],
                    values["relation"],
                )
        except self._psycopg.errors.UniqueViolation as exc:
            raise OwnerContactConflict("該關係人已連結此地主。") from exc

    def create_owner_contact_by_owner(self, user, owner_id, values):
        try:
            with self._connect() as conn:
                return self._owner_contact_service(conn).create_new(
                    owner_id,
                    user,
                    values["contact"],
                    values["relation"],
                )
        except self._psycopg.errors.UniqueViolation as exc:
            raise OwnerContactConflict("該關係人已連結此地主。") from exc

    def link_owner_contact(self, user, record_id, values):
        try:
            with self._connect() as conn:
                owner_id = self._owner_id_for_record(conn, record_id)
                return self._owner_contact_service(conn).link_existing(
                    owner_id,
                    user,
                    values["contact_id"],
                    values["relation"],
                )
        except self._psycopg.errors.UniqueViolation as exc:
            raise OwnerContactConflict("該關係人已連結此地主。") from exc

    def link_owner_contact_by_owner(self, user, owner_id, values):
        try:
            with self._connect() as conn:
                return self._owner_contact_service(conn).link_existing(
                    owner_id,
                    user,
                    values["contact_id"],
                    values["relation"],
                )
        except self._psycopg.errors.UniqueViolation as exc:
            raise OwnerContactConflict("該關係人已連結此地主。") from exc

    def update_owner_contact(self, user, record_id, relation_id, values):
        try:
            with self._connect() as conn:
                owner_id = self._owner_id_for_record(conn, record_id)
                return self._owner_contact_service(conn).update(
                    owner_id,
                    relation_id,
                    user,
                    values["contact"],
                    values["relation"],
                    expected_contact_updated_at=values.get(
                        "expected_contact_updated_at"
                    ),
                    expected_relation_updated_at=values.get(
                        "expected_relation_updated_at"
                    ),
                )
        except self._psycopg.errors.UniqueViolation as exc:
            raise OwnerContactConflict(
                "同一地主只能有一位主要關係人，請重新整理後再試。"
            ) from exc

    def update_owner_contact_by_owner(
        self, user, owner_id, relation_id, values
    ):
        try:
            with self._connect() as conn:
                return self._owner_contact_service(conn).update(
                    owner_id,
                    relation_id,
                    user,
                    values["contact"],
                    values["relation"],
                    expected_contact_updated_at=values.get(
                        "expected_contact_updated_at"
                    ),
                    expected_relation_updated_at=values.get(
                        "expected_relation_updated_at"
                    ),
                )
        except self._psycopg.errors.UniqueViolation as exc:
            raise OwnerContactConflict(
                "同一地主只能有一位主要關係人，請重新整理後再試。"
            ) from exc

    def deactivate_owner_contact(
        self, user, record_id, relation_id, values=None
    ):
        values = dict(values or {})
        with self._connect() as conn:
            owner_id = self._owner_id_for_record(conn, record_id)
            return self._owner_contact_service(conn).deactivate(
                owner_id,
                relation_id,
                user,
                reason=values.get("reason", ""),
                expected_relation_updated_at=values.get(
                    "expected_relation_updated_at"
                ),
            )

    def deactivate_owner_contact_by_owner(
        self, user, owner_id, relation_id, values=None
    ):
        values = dict(values or {})
        with self._connect() as conn:
            return self._owner_contact_service(conn).deactivate(
                owner_id,
                relation_id,
                user,
                reason=values.get("reason", ""),
                expected_relation_updated_at=values.get(
                    "expected_relation_updated_at"
                ),
            )

    def reactivate_owner_contact(
        self, user, record_id, relation_id, values=None
    ):
        values = dict(values or {})
        try:
            with self._connect() as conn:
                owner_id = self._owner_id_for_record(conn, record_id)
                return self._owner_contact_service(conn).reactivate(
                    owner_id,
                    relation_id,
                    user,
                    expected_relation_updated_at=values.get(
                        "expected_relation_updated_at"
                    ),
                )
        except self._psycopg.errors.UniqueViolation as exc:
            raise OwnerContactConflict("該關係人已連結此地主。") from exc

    def reactivate_owner_contact_by_owner(
        self, user, owner_id, relation_id, values=None
    ):
        values = dict(values or {})
        try:
            with self._connect() as conn:
                return self._owner_contact_service(conn).reactivate(
                    owner_id,
                    relation_id,
                    user,
                    expected_relation_updated_at=values.get(
                        "expected_relation_updated_at"
                    ),
                )
        except self._psycopg.errors.UniqueViolation as exc:
            raise OwnerContactConflict("該關係人已連結此地主。") from exc
