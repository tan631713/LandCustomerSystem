import unittest

from fastapi.testclient import TestClient

from customer_api.app import create_app
from customer_api.config import ApiSettings
from customer_api.owner_contact_service import (
    OwnerContactConflict,
    OwnerContactNotFound,
)
from customer_api.types import AuthenticatedUser


class _OwnerContactApiSource:
    backend_name = "test"

    def __init__(self):
        self.calls = []
        self.users = {
            role: AuthenticatedUser(
                id=index,
                username=role,
                display_name=role.title(),
                role=role,
                data_key=b"x" * 32,
            )
            for index, role in enumerate(("admin", "editor", "viewer"), start=1)
        }
        self.item = {
            "relation_id": 9,
            "owner_id": 3,
            "contact_id": 4,
            "name": "王小明",
            "relationship_type": "兒子",
            "relationship_note": "長子",
            "mobile_phone": "0912",
            "home_phone": "",
            "registered_address": "桃園市",
            "contact_address": "台中市",
            "work_address": "",
            "identity_note": "長子",
            "is_primary": True,
            "sort_order": 10,
            "contact_notes": "",
            "relation_notes": "",
            "is_active": True,
            "contact_updated_at": "2026-07-29T10:00:00+08:00",
            "relation_updated_at": "2026-07-29T10:00:00+08:00",
        }

    def health(self):
        return {"status": "ok", "backend": "test", "schema_version": 10}

    def authenticate(self, username, password):
        if password != "correct-password":
            return None
        return self.users.get(username)

    def list_owner_contacts(self, user, record_id, include_inactive=False):
        self.calls.append(("list", user.role, record_id, include_inactive))
        if record_id == 404:
            raise OwnerContactNotFound("地主不存在。")
        return {"owner_id": 3, "items": [dict(self.item)]}

    def get_owner_contact_relation(self, user, record_id, relation_id):
        self.calls.append(("get", user.role, record_id, relation_id))
        if record_id != 7 or relation_id != 9:
            raise OwnerContactNotFound("關係不存在。")
        return dict(self.item)

    def search_owner_contacts(self, user, query, limit=50):
        self.calls.append(("search", user.role, query, limit))
        return [
            {
                "id": 4,
                "name": "王小明",
                "mobile_phone": "0912",
                "home_phone": "",
                "registered_address": "桃園市",
                "contact_address": "台中市",
                "owner_count": 2,
            }
        ]

    def find_owner_contact_duplicates(self, user, **values):
        self.calls.append(("duplicates", user.role, values))
        return [{"id": 4, "name": "王小明", "owner_count": 2}]

    def create_owner_contact(self, user, record_id, values):
        self.calls.append(("create", user.role, record_id, values))
        return dict(self.item)

    def link_owner_contact(self, user, record_id, values):
        self.calls.append(("link", user.role, record_id, values))
        if values["contact_id"] == 99:
            raise OwnerContactConflict("該關係人已連結此地主。")
        return dict(self.item)

    def update_owner_contact(self, user, record_id, relation_id, values):
        self.calls.append(("update", user.role, record_id, relation_id, values))
        if record_id != 7 or relation_id != 9:
            raise OwnerContactNotFound("關係不存在。")
        return dict(self.item)

    def deactivate_owner_contact(
        self, user, record_id, relation_id, values=None
    ):
        self.calls.append(
            ("deactivate", user.role, record_id, relation_id, values or {})
        )
        return {**self.item, "is_active": False, "is_primary": False}

    def reactivate_owner_contact(
        self, user, record_id, relation_id, values=None
    ):
        self.calls.append(
            ("reactivate", user.role, record_id, relation_id, values or {})
        )
        return {**self.item, "is_active": True, "is_primary": False}

    def list_owner_contacts_by_owner(
        self, user, owner_id, include_inactive=False
    ):
        return self.list_owner_contacts(user, owner_id, include_inactive)

    def get_owner_contact_relation_by_owner(
        self, user, owner_id, relation_id
    ):
        return self.get_owner_contact_relation(user, 7, relation_id)

    def create_owner_contact_by_owner(self, user, owner_id, values):
        return self.create_owner_contact(user, owner_id, values)

    def link_owner_contact_by_owner(self, user, owner_id, values):
        return self.link_owner_contact(user, owner_id, values)

    def update_owner_contact_by_owner(
        self, user, owner_id, relation_id, values
    ):
        return self.update_owner_contact(user, 7, relation_id, values)

    def deactivate_owner_contact_by_owner(
        self, user, owner_id, relation_id, values=None
    ):
        return self.deactivate_owner_contact(
            user, owner_id, relation_id, values
        )

    def reactivate_owner_contact_by_owner(
        self, user, owner_id, relation_id, values=None
    ):
        return self.reactivate_owner_contact(
            user, owner_id, relation_id, values
        )


class OwnerContactApiTests(unittest.TestCase):
    def setUp(self):
        self.source = _OwnerContactApiSource()
        self.app = create_app(
            settings=ApiSettings(backend="sqlite"),
            data_source=self.source,
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()

    def login(self, role):
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": role, "password": "correct-password"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    @staticmethod
    def payload():
        return {
            "contact": {
                "name": "王小明",
                "mobile_phone": "0912",
                "home_phone": "",
                "registered_address": "桃園市",
                "contact_address": "台中市",
                "work_address": "",
                "identity_note": "長子",
                "notes": "",
            },
            "relation": {
                "relationship_type": "兒子",
                "relationship_note": "長子",
                "is_primary": True,
                "sort_order": 10,
                "notes": "",
            },
        }

    def test_viewer_can_list_detail_search_and_duplicates(self):
        headers = self.login("viewer")
        listed = self.client.get(
            "/api/v1/records/7/owner-contacts",
            params={"include_inactive": True},
            headers=headers,
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["name"], "王小明")

        detail = self.client.get(
            "/api/v1/records/7/owner-contacts/9", headers=headers
        )
        self.assertEqual(detail.status_code, 200, detail.text)

        searched = self.client.get(
            "/api/v1/contacts/search",
            params={"q": "0912"},
            headers=headers,
        )
        self.assertEqual(searched.status_code, 200, searched.text)
        self.assertEqual(searched.json()["items"][0]["owner_count"], 2)

        duplicates = self.client.post(
            "/api/v1/contacts/duplicate-check",
            json={"name": "王小明", "mobile_phone": "0912"},
            headers=headers,
        )
        self.assertEqual(duplicates.status_code, 200, duplicates.text)

    def test_viewer_cannot_write(self):
        response = self.client.post(
            "/api/v1/records/7/owner-contacts",
            json=self.payload(),
            headers=self.login("viewer"),
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_editor_can_create_link_update_deactivate_and_reactivate(self):
        headers = self.login("editor")
        created = self.client.post(
            "/api/v1/records/7/owner-contacts",
            json=self.payload(),
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)

        linked = self.client.post(
            "/api/v1/records/7/owner-contacts/link",
            json={"contact_id": 4, "relation": self.payload()["relation"]},
            headers=headers,
        )
        self.assertEqual(linked.status_code, 201, linked.text)

        updated = self.client.put(
            "/api/v1/records/7/owner-contacts/9",
            json=self.payload(),
            headers=headers,
        )
        self.assertEqual(updated.status_code, 200, updated.text)

        deactivated = self.client.post(
            "/api/v1/records/7/owner-contacts/9/deactivate",
            json={"reason": "不再協助地主"},
            headers=headers,
        )
        self.assertEqual(deactivated.status_code, 200, deactivated.text)
        self.assertFalse(deactivated.json()["item"]["is_active"])

        reactivated = self.client.post(
            "/api/v1/records/7/owner-contacts/9/reactivate", headers=headers
        )
        self.assertEqual(reactivated.status_code, 200, reactivated.text)
        self.assertFalse(reactivated.json()["item"]["is_primary"])

    def test_owner_mismatch_not_found_and_duplicate_conflict(self):
        headers = self.login("editor")
        mismatch = self.client.put(
            "/api/v1/records/8/owner-contacts/9",
            json=self.payload(),
            headers=headers,
        )
        self.assertEqual(mismatch.status_code, 404, mismatch.text)

        duplicate = self.client.post(
            "/api/v1/records/7/owner-contacts/link",
            json={"contact_id": 99, "relation": self.payload()["relation"]},
            headers=headers,
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

    def test_input_validation_rejects_blank_name_and_other_without_note(self):
        headers = self.login("editor")
        payload = self.payload()
        payload["contact"]["name"] = " "
        blank = self.client.post(
            "/api/v1/records/7/owner-contacts",
            json=payload,
            headers=headers,
        )
        self.assertEqual(blank.status_code, 422, blank.text)

        payload = self.payload()
        payload["relation"]["relationship_type"] = "其他"
        payload["relation"]["relationship_note"] = ""
        other = self.client.post(
            "/api/v1/records/7/owner-contacts",
            json=payload,
            headers=headers,
        )
        self.assertEqual(other.status_code, 422, other.text)

        payload = self.payload()
        payload["contact"]["registered_address"] = "長" * 500
        accepted = self.client.post(
            "/api/v1/records/7/owner-contacts",
            json=payload,
            headers=headers,
        )
        self.assertEqual(accepted.status_code, 201, accepted.text)
        payload["contact"]["registered_address"] += "址"
        rejected = self.client.post(
            "/api/v1/records/7/owner-contacts",
            json=payload,
            headers=headers,
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)

    def test_canonical_owner_routes_share_the_same_service_boundary(self):
        headers = self.login("editor")
        listed = self.client.get(
            "/api/v1/owners/3/contacts", headers=headers
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        created = self.client.post(
            "/api/v1/owners/3/contacts",
            json=self.payload(),
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        detail = self.client.get(
            "/api/v1/owners/3/contacts/9", headers=headers
        )
        self.assertEqual(detail.status_code, 200, detail.text)


if __name__ == "__main__":
    unittest.main()
