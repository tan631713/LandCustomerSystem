"""Business rules for reusable people related to a land owner."""

from __future__ import annotations

from dataclasses import dataclass

from customer_domain import normalize_taiwan_identity
from customer_owner_contact_types import RELATIONSHIP_TYPES


class OwnerContactError(ValueError):
    """Base class for an expected owner-contact workflow failure."""


class OwnerContactNotFound(OwnerContactError):
    pass


class OwnerContactConflict(OwnerContactError):
    pass


class OwnerContactConcurrentUpdate(OwnerContactConflict):
    pass


def _clean(value, maximum):
    result = str(value or "").strip()
    if len(result) > maximum:
        raise OwnerContactError(f"輸入內容不可超過 {maximum} 個字。")
    return result


def normalize_contact_values(values, *, allow_identity_preserve=False):
    source = dict(values or {})
    raw_external_id = source.get("external_id")
    if allow_identity_preserve and raw_external_id is None:
        external_id = None
    else:
        try:
            external_id = normalize_taiwan_identity(raw_external_id)
        except ValueError as exc:
            raise OwnerContactError(str(exc)) from exc
        if "*" in external_id:
            raise OwnerContactError("請輸入完整且正確的身分證字號。")
    normalized = {
        "name": _clean(source.get("name"), 100),
        "external_id": external_id,
        "mobile_phone": _clean(source.get("mobile_phone"), 30),
        "home_phone": _clean(source.get("home_phone"), 30),
        "registered_address": _clean(source.get("registered_address"), 500),
        "contact_address": _clean(source.get("contact_address"), 500),
        "work_address": _clean(source.get("work_address"), 500),
        "identity_note": _clean(source.get("identity_note"), 300),
        "notes": _clean(source.get("notes"), 2000),
    }
    if not normalized["name"]:
        raise OwnerContactError("姓名不可空白。")
    return normalized


def normalize_relation_values(values):
    source = dict(values or {})
    relationship_type = _clean(source.get("relationship_type"), 50)
    relationship_note = _clean(source.get("relationship_note"), 100)
    if not relationship_type:
        raise OwnerContactError("關係類型不可空白。")
    if relationship_type not in RELATIONSHIP_TYPES:
        raise OwnerContactError("關係類型不在允許清單中。")
    if relationship_type == "其他" and not relationship_note:
        raise OwnerContactError("選擇「其他」時必須填寫關係補充。")
    try:
        sort_order = int(source.get("sort_order") or 0)
    except (TypeError, ValueError) as exc:
        raise OwnerContactError("排序必須是整數。") from exc
    if sort_order < 0 or sort_order > 1_000_000:
        raise OwnerContactError("排序必須介於 0 到 1000000。")
    return {
        "relationship_type": relationship_type,
        "relationship_note": relationship_note,
        "is_primary": bool(source.get("is_primary")),
        "sort_order": sort_order,
        "notes": _clean(source.get("notes"), 2000),
    }


@dataclass
class OwnerContactService:
    """Coordinate contact and relation repositories in one caller transaction."""

    contacts: object
    relations: object
    audit: object
    identity_encoder: object = lambda value: value

    def _set_primary(self, owner_id, relation_id, actor):
        previous_items = self.relations.set_primary(owner_id, relation_id) or []
        for previous in previous_items:
            self.audit(
                actor,
                "取消主要關係人",
                owner_id,
                previous["contact_id"],
                previous["relation_id"],
                previous,
                {**previous, "is_primary": False},
            )

    def create_new(self, owner_id, actor, contact_values, relation_values):
        self.relations.require_owner(owner_id)
        contact = normalize_contact_values(contact_values)
        contact["external_id"] = self.identity_encoder(contact["external_id"])
        relation = normalize_relation_values(relation_values)
        contact_id = self.contacts.create(contact)
        relation_id = self.relations.create(owner_id, contact_id, relation)
        if relation["is_primary"]:
            self._set_primary(owner_id, relation_id, actor)
        result = self.relations.get(owner_id, relation_id)
        self.audit(
            actor,
            "新增全新關係人",
            owner_id,
            contact_id,
            relation_id,
            None,
            result,
        )
        if relation["is_primary"]:
            self.audit(
                actor,
                "設為主要關係人",
                owner_id,
                contact_id,
                relation_id,
                None,
                result,
            )
        return result

    def link_existing(self, owner_id, actor, contact_id, relation_values):
        self.relations.require_owner(owner_id)
        self.contacts.require_active(contact_id)
        if self.relations.exists(owner_id, contact_id, active_only=True):
            raise OwnerContactConflict("該關係人已連結此地主。")
        relation = normalize_relation_values(relation_values)
        relation_id = self.relations.create(owner_id, contact_id, relation)
        if relation["is_primary"]:
            self._set_primary(owner_id, relation_id, actor)
        result = self.relations.get(owner_id, relation_id)
        self.audit(
            actor,
            "連結既有關係人",
            owner_id,
            contact_id,
            relation_id,
            None,
            result,
        )
        if relation["is_primary"]:
            self.audit(
                actor,
                "設為主要關係人",
                owner_id,
                contact_id,
                relation_id,
                None,
                result,
            )
        return result

    def update(
        self,
        owner_id,
        relation_id,
        actor,
        contact_values,
        relation_values,
        *,
        expected_contact_updated_at=None,
        expected_relation_updated_at=None,
    ):
        before = self.relations.get(owner_id, relation_id)
        if before is None:
            raise OwnerContactNotFound("關係不存在。")
        contact = normalize_contact_values(
            contact_values, allow_identity_preserve=True
        )
        if contact["external_id"] is None:
            contact["external_id"] = before.get("external_id") or ""
        else:
            contact["external_id"] = self.identity_encoder(
                contact["external_id"]
            )
        relation = normalize_relation_values(relation_values)
        self.contacts.update(
            before["contact_id"],
            contact,
            expected_updated_at=expected_contact_updated_at,
        )
        self.relations.update(
            owner_id,
            relation_id,
            relation,
            expected_updated_at=expected_relation_updated_at,
        )
        if relation["is_primary"]:
            self._set_primary(owner_id, relation_id, actor)
        result = self.relations.get(owner_id, relation_id)
        contact_before = {
            "name": before.get("name") or "",
            "external_id": before.get("external_id") or "",
            "mobile_phone": before.get("mobile_phone") or "",
            "home_phone": before.get("home_phone") or "",
            "registered_address": before.get("registered_address") or "",
            "contact_address": before.get("contact_address") or "",
            "work_address": before.get("work_address") or "",
            "identity_note": before.get("identity_note") or "",
            "notes": before.get("contact_notes") or "",
        }
        relation_before = {
            "relationship_type": before.get("relationship_type") or "",
            "relationship_note": before.get("relationship_note") or "",
            "is_primary": bool(before.get("is_primary")),
            "sort_order": int(before.get("sort_order") or 0),
            "notes": before.get("relation_notes") or "",
        }
        if contact_before != contact:
            self.audit(
                actor,
                "修改關係人共用資料",
                owner_id,
                before["contact_id"],
                relation_id,
                before,
                result,
            )
        if relation_before != relation:
            self.audit(
                actor,
                "修改地主關係資料",
                owner_id,
                before["contact_id"],
                relation_id,
                before,
                result,
            )
        if relation["is_primary"] and not relation_before["is_primary"]:
            self.audit(
                actor,
                "設為主要關係人",
                owner_id,
                before["contact_id"],
                relation_id,
                before,
                result,
            )
        elif relation_before["is_primary"] and not relation["is_primary"]:
            self.audit(
                actor,
                "取消主要關係人",
                owner_id,
                before["contact_id"],
                relation_id,
                before,
                result,
            )
        return result

    def deactivate(
        self,
        owner_id,
        relation_id,
        actor,
        *,
        reason="",
        expected_relation_updated_at=None,
    ):
        before = self.relations.get(owner_id, relation_id)
        if before is None:
            raise OwnerContactNotFound("關係不存在。")
        if not before["is_active"]:
            raise OwnerContactConflict("關係已停用。")
        reason = _clean(reason, 500)
        self.relations.deactivate(
            owner_id,
            relation_id,
            actor_id=actor.id,
            expected_updated_at=expected_relation_updated_at,
        )
        result = self.relations.get(owner_id, relation_id)
        audited_after = {**result, "deactivation_reason": reason}
        self.audit(
            actor,
            "停用關係",
            owner_id,
            before["contact_id"],
            relation_id,
            before,
            audited_after,
        )
        if before.get("is_primary"):
            self.audit(
                actor,
                "取消主要關係人",
                owner_id,
                before["contact_id"],
                relation_id,
                before,
                result,
            )
        return result

    def reactivate(
        self,
        owner_id,
        relation_id,
        actor,
        *,
        expected_relation_updated_at=None,
    ):
        before = self.relations.get(owner_id, relation_id)
        if before is None:
            raise OwnerContactNotFound("關係不存在。")
        if before["is_active"]:
            raise OwnerContactConflict("關係已啟用。")
        self.contacts.require_active(before["contact_id"])
        if self.relations.exists(
            owner_id,
            before["contact_id"],
            active_only=True,
            excluding_relation_id=relation_id,
        ):
            raise OwnerContactConflict("該關係人已連結此地主。")
        self.relations.reactivate(
            owner_id,
            relation_id,
            expected_updated_at=expected_relation_updated_at,
        )
        result = self.relations.get(owner_id, relation_id)
        self.audit(
            actor,
            "重新啟用關係",
            owner_id,
            before["contact_id"],
            relation_id,
            before,
            result,
        )
        return result
