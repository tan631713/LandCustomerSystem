import unittest

from customer_api.owner_contact_service import (
    OwnerContactConflict,
    OwnerContactNotFound,
    OwnerContactService,
    normalize_contact_values,
    normalize_relation_values,
)


class _Actor:
    id = 7
    username = "editor"


class _Contacts:
    def __init__(self):
        self.rows = {}
        self.next_id = 1

    def create(self, values):
        contact_id = self.next_id
        self.next_id += 1
        self.rows[contact_id] = {
            "id": contact_id,
            **values,
            "is_active": True,
            "updated_at": "2026-07-29T10:00:00+08:00",
        }
        return contact_id

    def get(self, contact_id):
        row = self.rows.get(int(contact_id))
        return dict(row) if row else None

    def require_active(self, contact_id):
        row = self.get(contact_id)
        if not row:
            raise OwnerContactNotFound("關係人不存在。")
        if not row["is_active"]:
            raise OwnerContactConflict("關係人已停用。")
        return row

    def update(self, contact_id, values, **_options):
        self.require_active(contact_id)
        self.rows[int(contact_id)].update(values)


class _Relations:
    def __init__(self, contacts):
        self.contacts = contacts
        self.rows = {}
        self.next_id = 1
        self.owners = {1, 2}

    def require_owner(self, owner_id):
        if int(owner_id) not in self.owners:
            raise OwnerContactNotFound("地主不存在。")

    def exists(
        self,
        owner_id,
        contact_id,
        *,
        active_only=True,
        excluding_relation_id=None,
    ):
        return any(
            row["owner_id"] == int(owner_id)
            and row["contact_id"] == int(contact_id)
            and (not active_only or row["is_active"])
            and row["id"] != excluding_relation_id
            for row in self.rows.values()
        )

    def create(self, owner_id, contact_id, values):
        if self.exists(owner_id, contact_id, active_only=True):
            raise OwnerContactConflict("該關係人已連結此地主。")
        relation_id = self.next_id
        self.next_id += 1
        self.rows[relation_id] = {
            "id": relation_id,
            "owner_id": int(owner_id),
            "contact_id": int(contact_id),
            **values,
            "is_primary": False,
            "is_active": True,
            "relation_updated_at": "2026-07-29T10:00:00+08:00",
        }
        return relation_id

    def get(self, owner_id, relation_id):
        relation = self.rows.get(int(relation_id))
        if not relation or relation["owner_id"] != int(owner_id):
            return None
        contact = self.contacts.get(relation["contact_id"])
        if not contact:
            return None
        return {
            "relation_id": relation["id"],
            **relation,
            "name": contact["name"],
            "mobile_phone": contact["mobile_phone"],
            "home_phone": contact["home_phone"],
            "registered_address": contact["registered_address"],
            "contact_address": contact["contact_address"],
            "work_address": contact["work_address"],
            "identity_note": contact["identity_note"],
            "contact_notes": contact["notes"],
            "contact_updated_at": contact["updated_at"],
            "relation_notes": relation["notes"],
            "owner_count": sum(
                1
                for row in self.rows.values()
                if row["contact_id"] == relation["contact_id"] and row["is_active"]
            ),
        }

    def update(self, owner_id, relation_id, values, **_options):
        row = self.rows.get(int(relation_id))
        if not row or row["owner_id"] != int(owner_id):
            raise OwnerContactNotFound("關係不存在。")
        if not row["is_active"]:
            raise OwnerContactConflict("關係已停用。")
        row.update(values)
        row["is_primary"] = False

    def set_primary(self, owner_id, relation_id):
        target = self.get(owner_id, relation_id)
        if not target or not target["is_active"]:
            raise OwnerContactNotFound("關係不存在。")
        previous = [
            self.get(owner_id, row["id"])
            for row in self.rows.values()
            if row["owner_id"] == int(owner_id)
            and row["is_active"]
            and row["is_primary"]
            and row["id"] != int(relation_id)
        ]
        for row in self.rows.values():
            if row["owner_id"] == int(owner_id) and row["is_active"]:
                row["is_primary"] = row["id"] == int(relation_id)
        return previous

    def deactivate(
        self, owner_id, relation_id, *, actor_id, expected_updated_at=None
    ):
        del expected_updated_at
        row = self.rows[int(relation_id)]
        if row["owner_id"] != int(owner_id) or not row["is_active"]:
            raise OwnerContactConflict("關係已停用。")
        row["is_active"] = False
        row["is_primary"] = False
        row["deactivated_at"] = "2026-07-29T12:00:00+08:00"
        row["deactivated_by"] = int(actor_id)

    def reactivate(self, owner_id, relation_id, *, expected_updated_at=None):
        del expected_updated_at
        row = self.rows[int(relation_id)]
        if row["owner_id"] != int(owner_id) or row["is_active"]:
            raise OwnerContactConflict("關係已啟用。")
        row["is_active"] = True
        row["is_primary"] = False
        row["deactivated_at"] = None
        row["deactivated_by"] = None


class OwnerContactServiceTests(unittest.TestCase):
    def setUp(self):
        self.contacts = _Contacts()
        self.relations = _Relations(self.contacts)
        self.audits = []
        self.service = OwnerContactService(
            self.contacts,
            self.relations,
            lambda *values: self.audits.append(values),
        )
        self.actor = _Actor()
        self.contact = {
            "name": "王小明",
            "mobile_phone": "0912-345-678",
            "home_phone": "",
            "registered_address": "桃園市",
            "contact_address": "台中市",
            "work_address": "五金行",
            "identity_note": "長子，住台中",
            "notes": "由鄰居提供資料",
        }
        self.relation = {
            "relationship_type": "兒子",
            "relationship_note": "長子",
            "is_primary": True,
            "sort_order": 10,
            "notes": "優先聯絡",
        }

    def test_other_relationship_requires_supplement(self):
        with self.assertRaisesRegex(ValueError, "關係補充"):
            normalize_relation_values(
                {"relationship_type": "其他", "relationship_note": ""}
            )

    def test_contact_validation_trims_and_limits_enhanced_fields(self):
        normalized = normalize_contact_values(
            {
                **self.contact,
                "name": "  王小明  ",
                "contact_address": "  台中市  ",
            }
        )
        self.assertEqual(normalized["name"], "王小明")
        self.assertEqual(normalized["contact_address"], "台中市")
        with self.assertRaisesRegex(ValueError, "500"):
            normalize_contact_values(
                {**self.contact, "registered_address": "地" * 501}
            )

    def test_create_new_sets_one_primary_and_audits(self):
        first = self.service.create_new(
            1, self.actor, self.contact, self.relation
        )
        second = self.service.create_new(
            1,
            self.actor,
            {**self.contact, "name": "王小華", "mobile_phone": "0922"},
            {**self.relation, "relationship_type": "女兒"},
        )
        self.assertFalse(self.relations.rows[first["relation_id"]]["is_primary"])
        self.assertTrue(self.relations.rows[second["relation_id"]]["is_primary"])
        actions = [entry[1] for entry in self.audits]
        self.assertIn("新增全新關係人", actions)
        self.assertIn("設為主要關係人", actions)
        self.assertIn("取消主要關係人", actions)

    def test_link_existing_rejects_missing_and_duplicate(self):
        with self.assertRaises(OwnerContactNotFound):
            self.service.link_existing(1, self.actor, 999, self.relation)
        contact_id = self.contacts.create(self.contact)
        self.service.link_existing(1, self.actor, contact_id, self.relation)
        with self.assertRaises(OwnerContactConflict):
            self.service.link_existing(1, self.actor, contact_id, self.relation)
        other = self.service.link_existing(
            2, self.actor, contact_id, {**self.relation, "is_primary": False}
        )
        self.assertEqual(other["owner_id"], 2)

    def test_edit_contact_is_shared_but_relation_is_owner_specific(self):
        contact_id = self.contacts.create(self.contact)
        first = self.service.link_existing(1, self.actor, contact_id, self.relation)
        second = self.service.link_existing(
            2,
            self.actor,
            contact_id,
            {**self.relation, "relationship_type": "代理人", "is_primary": False},
        )
        self.service.update(
            1,
            first["relation_id"],
            self.actor,
            {
                **self.contact,
                "name": "王大明",
                "contact_address": "新北市",
            },
            {**self.relation, "relationship_type": "兄弟", "is_primary": False},
        )
        self.assertEqual(
            self.relations.get(2, second["relation_id"])["name"], "王大明"
        )
        self.assertEqual(
            self.relations.get(2, second["relation_id"])["contact_address"],
            "新北市",
        )
        self.assertEqual(
            self.relations.get(2, second["relation_id"])["relationship_type"],
            "代理人",
        )
        actions = [entry[1] for entry in self.audits]
        self.assertIn("修改關係人共用資料", actions)
        self.assertIn("修改地主關係資料", actions)

    def test_deactivate_and_reactivate_do_not_restore_primary(self):
        created = self.service.create_new(
            1, self.actor, self.contact, self.relation
        )
        relation_id = created["relation_id"]
        self.service.deactivate(
            1, relation_id, self.actor, reason="不再協助地主"
        )
        self.assertFalse(self.relations.rows[relation_id]["is_active"])
        self.assertFalse(self.relations.rows[relation_id]["is_primary"])
        self.assertEqual(self.relations.rows[relation_id]["deactivated_by"], 7)
        self.service.reactivate(1, relation_id, self.actor)
        self.assertTrue(self.relations.rows[relation_id]["is_active"])
        self.assertFalse(self.relations.rows[relation_id]["is_primary"])
        self.assertIsNone(self.relations.rows[relation_id]["deactivated_at"])
        audited_after = [
            entry[-1]
            for entry in self.audits
            if entry[1] == "停用關係"
        ][0]
        self.assertEqual(audited_after["deactivation_reason"], "不再協助地主")
        self.assertIn("重新啟用關係", [entry[1] for entry in self.audits])

    def test_relation_owner_mismatch_is_rejected(self):
        created = self.service.create_new(
            1, self.actor, self.contact, self.relation
        )
        with self.assertRaises(OwnerContactNotFound):
            self.service.update(
                2,
                created["relation_id"],
                self.actor,
                self.contact,
                self.relation,
            )


if __name__ == "__main__":
    unittest.main()
