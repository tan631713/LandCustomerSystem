"""Existing-owner suggestions for a record typed in by hand (PostgreSQL).

The desktop sends what was typed into 姓名／身分證／地址 when the name field
loses focus.  Matching happens here because names, identity numbers and
addresses are stored as Fernet ciphertext: the server decrypts, compares and
answers with masked identity numbers and phones only.
"""

from customer_owner_match import (
    DEFAULT_CANDIDATE_LIMIT,
    candidate_response_item,
    identity_is_placeholder,
    normalize_owner_name,
    rank_owner_candidates,
)
from customer_postgres_keys import owner_key_for
from customer_security import decrypt_value, make_fernet


class OwnerAttachError(ValueError):
    """The chosen owner cannot take this record (shown to the user as is)."""


class PostgreSQLOwnerMatchMixin:
    def _owner_match_rows(self, conn, fernet):
        rows = conn.execute(
            """
            SELECT owner.id AS owner_id, owner.owner_key, owner.owner_name,
                   owner.external_id, owner.address, owner.phone,
                   COUNT(ownership.id) AS land_count,
                   MIN(ownership.id) AS sample_record_id
            FROM owners owner
            JOIN ownerships ownership ON ownership.owner_id = owner.id
            GROUP BY owner.id
            """
        ).fetchall()
        owners = []
        for row in rows:
            owners.append(
                {
                    "owner_id": int(row["owner_id"]),
                    "owner_key": row.get("owner_key"),
                    "owner_name": decrypt_value(fernet, row.get("owner_name")) or "",
                    "external_id": decrypt_value(fernet, row.get("external_id")) or "",
                    "address": decrypt_value(fernet, row.get("address")) or "",
                    "phones": [
                        value
                        for value in [decrypt_value(fernet, row.get("phone"))]
                        if value
                    ],
                    "land_count": int(row.get("land_count") or 0),
                    "sample_record_id": int(row["sample_record_id"]),
                }
            )
        return owners

    @staticmethod
    def _owner_match_contact_phones(conn, owner_ids):
        if not owner_ids:
            return {}
        rows = conn.execute(
            """
            SELECT relation.owner_id, contact.mobile_phone, contact.home_phone
            FROM owner_contact_relations relation
            JOIN contacts contact ON contact.id = relation.contact_id
            WHERE relation.is_active = TRUE AND contact.is_active = TRUE
              AND relation.owner_id = ANY(%s)
            """,
            (list(owner_ids),),
        ).fetchall()
        phones = {}
        for row in rows:
            for key in ("mobile_phone", "home_phone"):
                if row.get(key):
                    phones.setdefault(int(row["owner_id"]), []).append(str(row[key]))
        return phones

    @staticmethod
    def _owner_match_lands(conn, owner_ids):
        if not owner_ids:
            return {}
        rows = conn.execute(
            """
            SELECT ownership.owner_id, land.district, land.section,
                   land.land_number
            FROM ownerships ownership
            JOIN lands land ON land.id = ownership.land_id
            WHERE ownership.owner_id = ANY(%s)
            ORDER BY ownership.owner_id, ownership.id
            """,
            (list(owner_ids),),
        ).fetchall()
        lands = {}
        for row in rows:
            label = "".join(
                str(row.get(key) or "") for key in ("district", "section")
            )
            label = f"{label} {row.get('land_number') or ''}".strip()
            lands.setdefault(int(row["owner_id"]), []).append(label)
        return lands

    @staticmethod
    def _owner_match_rejected_owner_ids(conn, owner_id):
        """Owners already marked "都不是" against ``owner_id``."""

        if owner_id is None:
            return set()
        rows = conn.execute(
            """
            SELECT DISTINCT CASE
                       WHEN left_ownership.owner_id = %s
                       THEN right_ownership.owner_id
                       ELSE left_ownership.owner_id
                   END AS other_owner_id
            FROM duplicate_reviews review
            JOIN ownerships left_ownership
              ON left_ownership.id = review.left_ownership_id
            JOIN ownerships right_ownership
              ON right_ownership.id = review.right_ownership_id
            WHERE review.decision = 'ignored'
              AND (left_ownership.owner_id = %s OR right_ownership.owner_id = %s)
            """,
            (int(owner_id), int(owner_id), int(owner_id)),
        ).fetchall()
        return {
            int(row["other_owner_id"])
            for row in rows
            if int(row["other_owner_id"]) != int(owner_id)
        }

    @staticmethod
    def _owner_match_rejected_for_records(conn, record_ids):
        """Owners rejected for the given (just created) records."""

        record_ids = [int(value) for value in record_ids or () if int(value) > 0]
        if not record_ids:
            return set()
        rows = conn.execute(
            """
            SELECT DISTINCT other.owner_id
            FROM duplicate_reviews review
            JOIN ownerships other
              ON other.id = CASE
                     WHEN review.left_ownership_id = ANY(%s)
                     THEN review.right_ownership_id
                     ELSE review.left_ownership_id
                 END
            WHERE review.decision = 'ignored'
              AND (review.left_ownership_id = ANY(%s)
                   OR review.right_ownership_id = ANY(%s))
            """,
            (record_ids, record_ids, record_ids),
        ).fetchall()
        return {int(row["owner_id"]) for row in rows}

    def owner_candidates(
        self, user, query, *, limit=DEFAULT_CANDIDATE_LIMIT, rejected_record_ids=()
    ):
        query = {
            "owner_name": str(query.get("owner_name") or "").strip(),
            "external_id": str(query.get("external_id") or "").strip(),
            "address": str(query.get("address") or "").strip(),
            "phone": str(query.get("phone") or "").strip(),
        }
        if not normalize_owner_name(query["owner_name"]) and not query["external_id"]:
            return {"items": [], "exact_owner_id": None}
        fernet = make_fernet(user.data_key)
        with self._connect() as conn:
            owners = self._owner_match_rows(conn, fernet)
            key_values = dict(query)
            if "*" in key_values["external_id"]:
                key_values["external_id"] = ""
            wanted_key = owner_key_for(key_values, user.data_key)
            exact_owner_id = next(
                (
                    owner["owner_id"]
                    for owner in owners
                    if owner.get("owner_key") == wanted_key
                ),
                None,
            )
            rejected = self._owner_match_rejected_owner_ids(conn, exact_owner_id)
            rejected |= self._owner_match_rejected_for_records(
                conn, rejected_record_ids
            )
            ranked = rank_owner_candidates(
                query,
                owners,
                ignored_owner_ids=rejected,
                exact_owner_id=exact_owner_id,
                limit=limit,
            )
            owner_ids = [item["owner_id"] for item in ranked]
            contact_phones = self._owner_match_contact_phones(conn, owner_ids)
            lands = self._owner_match_lands(conn, owner_ids)
        for item in ranked:
            owner = item["owner"]
            owner["phones"] = list(owner.get("phones") or []) + contact_phones.get(
                item["owner_id"], []
            )
            owner["lands"] = lands.get(item["owner_id"], [])
        # Phones of related people only become known for the short list, so
        # re-rank once with them (name + phone outranks name + address).
        if query["phone"]:
            ranked = rank_owner_candidates(
                query,
                [item["owner"] for item in ranked],
                ignored_owner_ids=rejected,
                exact_owner_id=exact_owner_id,
                limit=limit,
            )
        return {
            "items": [candidate_response_item(item) for item in ranked],
            "exact_owner_id": exact_owner_id,
        }

    def _attach_values_to_owner(self, conn, user, values, owner_id):
        """Values for a new ownership saved under an owner the user picked.

        The owners row itself is left alone (no owner_key change, nothing
        overwritten).  Fields the form only had as a mask or left blank take
        the owner's real value; a different complete identity number is
        refused rather than silently attached to the wrong person.
        """

        row = conn.execute(
            """
            SELECT id, owner_name, external_id, address, birth_year
            FROM owners WHERE id = %s
            """,
            (int(owner_id),),
        ).fetchone()
        if row is None:
            raise KeyError(owner_id)
        fernet = make_fernet(user.data_key)
        real = {
            key: decrypt_value(fernet, row.get(key)) or ""
            for key in ("owner_name", "external_id", "address", "birth_year")
        }
        values = dict(values)
        submitted_id = str(values.get("external_id") or "").strip()
        if identity_is_placeholder(submitted_id, real["external_id"]):
            values["external_id"] = real["external_id"] or None
        elif (
            real["external_id"]
            and submitted_id.upper() != real["external_id"].strip().upper()
        ):
            raise OwnerAttachError(
                "身分證與選擇的既有地主不同；請確認是不是同一人，"
                "或改按「都不是，新增新地主」。"
            )
        if not str(values.get("owner_name") or "").strip():
            values["owner_name"] = real["owner_name"]
        if not str(values.get("address") or "").strip():
            values["address"] = real["address"] or None
        if not str(values.get("birth_year") or "").strip() and real["birth_year"]:
            values["birth_year"] = real["birth_year"]
        values["name"] = values.get("owner_name") or ""
        return values
