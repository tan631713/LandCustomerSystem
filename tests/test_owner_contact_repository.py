import unittest

from customer_api.postgres_owner_contacts import (
    ContactRepository,
    OwnerContactRelationRepository,
)


class _Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Connection:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def execute(self, sql, parameters=()):
        normalized = " ".join(str(sql).split())
        parameters = tuple(parameters)
        self.calls.append((normalized, parameters))
        return self.handler(normalized, parameters)


class OwnerContactRepositoryTests(unittest.TestCase):
    def test_contact_create_get_update_search_and_duplicate_queries(self):
        stored = {
            "id": 4,
            "name": "王小明",
            "mobile_phone": "0912",
            "home_phone": "03-1234",
            "registered_address": "桃園市",
            "contact_address": "台中市",
            "work_address": "",
            "identity_note": "長子",
            "notes": "",
            "is_active": True,
            "created_at": "2026-07-29",
            "updated_at": "2026-07-29",
            "owner_count": 2,
        }

        def handler(sql, _parameters):
            if sql.startswith("INSERT INTO contacts"):
                return _Result([{"id": 4}])
            if sql.startswith("SELECT id, name"):
                return _Result([stored])
            if sql.startswith("UPDATE contacts"):
                return _Result([{"id": 4}])
            if "FROM contacts contact" in sql:
                return _Result([stored])
            raise AssertionError(sql)

        connection = _Connection(handler)
        repository = ContactRepository(connection)
        contact_id = repository.create(
            {
                "name": "王小明",
                "mobile_phone": "0912",
                "home_phone": "03-1234",
                "registered_address": "桃園市",
                "contact_address": "台中市",
                "work_address": "",
                "identity_note": "長子",
                "notes": "",
            }
        )
        self.assertEqual(contact_id, 4)
        self.assertEqual(repository.get(4)["name"], "王小明")
        repository.update(
            4,
            {
                "name": "王大明",
                "mobile_phone": "0912",
                "home_phone": "03-1234",
                "registered_address": "中壢區",
                "contact_address": "台中市",
                "work_address": "",
                "identity_note": "長子",
                "notes": "",
            },
            expected_updated_at="2026-07-29T10:00:00+08:00",
        )
        self.assertEqual(repository.search("王", limit=50)[0]["owner_count"], 2)
        self.assertEqual(
            repository.possible_duplicates(
                name="王小明", mobile_phone="0912", home_phone=""
            )[0]["id"],
            4,
        )
        search_call = next(
            call for call in connection.calls if "ILIKE" in call[0]
        )
        self.assertEqual(search_call[1][:3], ("%王%", "%王%", "%王%"))
        self.assertIn("REGEXP_REPLACE", search_call[0])
        update_call = next(
            call for call in connection.calls if call[0].startswith("UPDATE contacts")
        )
        self.assertIn("updated_at = CURRENT_TIMESTAMP", update_call[0])
        self.assertIn("updated_at = %s::timestamptz", update_call[0])

    def test_relation_list_sort_create_update_deactivate_and_reactivate(self):
        relation = {
            "relation_id": 8,
            "owner_id": 1,
            "contact_id": 4,
            "name": "王小明",
            "relationship_type": "兒子",
            "relationship_note": "",
            "mobile_phone": "0912",
            "home_phone": "(04)1234 5678",
            "registered_address": "",
            "contact_address": "",
            "work_address": "",
            "identity_note": "",
            "is_primary": True,
            "sort_order": 10,
            "contact_notes": "",
            "relation_notes": "",
            "is_active": True,
        }

        def handler(sql, _parameters):
            if sql.startswith("SELECT 1 FROM owner_contact_relations"):
                return _Result([])
            if sql.startswith("INSERT INTO owner_contact_relations"):
                return _Result([{"id": 8}])
            if sql.startswith("UPDATE owner_contact_relations"):
                return _Result([{"id": 8}])
            if "FROM owner_contact_relations relation" in sql:
                return _Result([relation])
            raise AssertionError(sql)

        connection = _Connection(handler)
        repository = OwnerContactRelationRepository(connection)
        listed = repository.list(1, include_inactive=True)
        self.assertEqual(listed[0]["relation_id"], 8)
        list_call = connection.calls[0]
        self.assertIn(
            "ORDER BY relation.is_primary DESC, relation.sort_order ASC, contact.name ASC, relation.id ASC",
            list_call[0],
        )
        self.assertEqual(list_call[1], (1, True))

        relation_id = repository.create(
            1,
            4,
            {
                "relationship_type": "兒子",
                "relationship_note": "",
                "sort_order": 10,
                "notes": "",
            },
        )
        self.assertEqual(relation_id, 8)
        repository.update(
            1,
            8,
            {
                "relationship_type": "代理人",
                "relationship_note": "",
                "sort_order": 20,
                "notes": "",
            },
        )
        update_call = next(
            call
            for call in connection.calls
            if call[0].startswith("UPDATE owner_contact_relations SET")
            and "relationship_type" in call[0]
        )
        self.assertIn("is_primary = FALSE", update_call[0])
        repository.deactivate(1, 8, actor_id=7)
        repository.reactivate(1, 8)
        self.assertTrue(
            any(
                "SET is_active = FALSE, is_primary = FALSE" in sql
                for sql, _parameters in connection.calls
            )
        )
        self.assertTrue(
            any(
                "SET is_active = TRUE, is_primary = FALSE" in sql
                for sql, _parameters in connection.calls
            )
        )

    def test_relation_exists_is_scoped_to_owner_and_contact(self):
        connection = _Connection(
            lambda sql, _parameters: _Result([{"exists": 1}])
            if sql.startswith("SELECT 1")
            else _Result()
        )
        repository = OwnerContactRelationRepository(connection)
        self.assertTrue(repository.exists(2, 9, active_only=True))
        sql, parameters = connection.calls[0]
        self.assertIn("owner_id = %s AND contact_id = %s AND is_active", sql)
        self.assertEqual(parameters, (2, 9))

    def test_phone_duplicate_search_normalizes_common_separators(self):
        stored = {
            "id": 4,
            "name": "王小明",
            "mobile_phone": "0912-345-678",
            "home_phone": "(04)1234 5678",
            "registered_address": "",
            "contact_address": "",
            "work_address": "",
            "identity_note": "",
            "notes": "",
            "is_active": True,
            "owner_count": 1,
        }
        connection = _Connection(
            lambda sql, _parameters: _Result([stored])
            if "FROM contacts contact" in sql
            else _Result()
        )
        repository = ContactRepository(connection)
        result = repository.possible_duplicates(
            name="", mobile_phone="0912 345 678"
        )
        self.assertEqual(result[0]["duplicate_strength"], "high")
        self.assertIn("手機相同", result[0]["duplicate_reasons"])
        sql, parameters = connection.calls[0]
        self.assertIn("REGEXP_REPLACE", sql)
        self.assertEqual(parameters[:2], ("0912345678", "0912345678"))
        home_result = repository.possible_duplicates(
            name="", home_phone="04-1234-5678"
        )
        self.assertIn("市話相同", home_result[0]["duplicate_reasons"])

    def test_name_and_address_are_high_duplicate_but_name_only_is_weak(self):
        stored = {
            "id": 5,
            "name": "李小美",
            "mobile_phone": "",
            "home_phone": "",
            "registered_address": "彰化縣員林市",
            "contact_address": "台中市西屯區",
            "work_address": "",
            "identity_note": "",
            "notes": "",
            "is_active": True,
            "owner_count": 1,
        }
        connection = _Connection(
            lambda sql, _parameters: _Result([stored])
            if "FROM contacts contact" in sql
            else _Result()
        )
        repository = ContactRepository(connection)
        high = repository.possible_duplicates(
            name="李小美", contact_address="台中市西屯區"
        )
        self.assertEqual(high[0]["duplicate_strength"], "high")
        self.assertIn("姓名及聯絡地址相同", high[0]["duplicate_reasons"])
        weak = repository.possible_duplicates(name="李小美")
        self.assertEqual(weak[0]["duplicate_strength"], "possible")
        self.assertEqual(weak[0]["duplicate_reasons"], ["姓名相同"])


if __name__ == "__main__":
    unittest.main()
