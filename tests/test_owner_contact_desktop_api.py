import json
import unittest
from urllib.parse import parse_qs, urlparse

from customer_desktop_api import DesktopApiClient, DesktopApiRecordRepository


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if self.payload is None:
            return b""
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class OwnerContactDesktopApiTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.item = {
            "relation_id": 9,
            "contact_id": 4,
            "name": "王小明",
            "is_active": True,
        }

        def opener(request, timeout):
            del timeout
            self.requests.append(request)
            parsed = urlparse(request.full_url)
            if parsed.path == "/api/v1/auth/login":
                return _Response(
                    {
                        "access_token": "token",
                        "user": {"username": "editor", "role": "editor"},
                    }
                )
            if parsed.path == "/api/v1/records/7/owner-contacts":
                if request.method == "GET":
                    return _Response({"items": [self.item]})
                return _Response({"item": self.item})
            if parsed.path == "/api/v1/records/7/owner-contacts/link":
                return _Response({"item": self.item})
            if parsed.path == "/api/v1/records/7/owner-contacts/9":
                return _Response({"item": self.item})
            if parsed.path == "/api/v1/records/7/owner-contacts/9/identity":
                return _Response({"external_id": "A123456789"})
            if parsed.path.endswith("/deactivate"):
                return _Response({"item": {**self.item, "is_active": False}})
            if parsed.path.endswith("/reactivate"):
                return _Response({"item": self.item})
            if parsed.path == "/api/v1/contacts/search":
                return _Response({"items": [{"id": 4, "name": "王小明"}]})
            if parsed.path == "/api/v1/contacts/duplicate-check":
                return _Response({"items": [{"id": 4, "name": "王小明"}]})
            raise AssertionError((request.method, request.full_url))

        self.client = DesktopApiClient(urlopen_fn=opener)
        self.client.login("editor", "secret")

    def test_client_uses_expected_paths_queries_and_payloads(self):
        self.assertEqual(
            self.client.list_owner_contacts(7, include_inactive=True)[0]["name"],
            "王小明",
        )
        self.assertEqual(self.client.get_owner_contact(7, 9)["contact_id"], 4)
        self.assertEqual(
            self.client.reveal_owner_contact_identity(7, 9), "A123456789"
        )
        self.assertEqual(
            self.client.search_owner_contacts("0912")[0]["id"], 4
        )
        self.assertEqual(
            self.client.find_owner_contact_duplicates(
                name="王小明", mobile="0912", home_phone="03"
            )[0]["id"],
            4,
        )
        payload = {
            "contact": {"name": "王小明"},
            "relation": {"relationship_type": "兒子"},
        }
        self.client.create_owner_contact(7, payload)
        self.client.link_owner_contact(
            7, {"contact_id": 4, "relation": payload["relation"]}
        )
        self.client.update_owner_contact(7, 9, payload)
        self.client.deactivate_owner_contact(7, 9)
        self.client.reactivate_owner_contact(7, 9)

        parsed_requests = [
            (request.method, urlparse(request.full_url), request)
            for request in self.requests[1:]
        ]
        list_query = parse_qs(parsed_requests[0][1].query)
        self.assertEqual(list_query["include_inactive"], ["True"])
        search = next(
            parsed for _method, parsed, _request in parsed_requests
            if parsed.path == "/api/v1/contacts/search"
        )
        self.assertEqual(parse_qs(search.query)["q"], ["0912"])
        duplicate_request = next(
            request for _method, parsed, request in parsed_requests
            if parsed.path == "/api/v1/contacts/duplicate-check"
        )
        duplicate_payload = json.loads(duplicate_request.data.decode("utf-8"))
        self.assertEqual(duplicate_payload["mobile_phone"], "0912")
        self.assertEqual(duplicate_payload["home_phone"], "03")
        write_methods = [
            method
            for method, parsed, _request in parsed_requests
            if "/owner-contacts" in parsed.path
            and method in {"POST", "PUT"}
        ]
        self.assertEqual(write_methods, ["POST", "POST", "PUT", "POST", "POST"])

    def test_record_repository_delegates_and_invalidates_after_writes(self):
        repository = DesktopApiRecordRepository(self.client, fernet=None)
        repository._rows = [{"id": 1}]
        self.assertEqual(repository.list_owner_contacts(7)[0]["contact_id"], 4)
        self.assertEqual(
            repository.reveal_owner_contact_identity(7, 9), "A123456789"
        )
        repository.create_owner_contact(
            7,
            {
                "contact": {"name": "王小明"},
                "relation": {"relationship_type": "兒子"},
            },
        )
        self.assertIsNone(repository._rows)
        repository.link_owner_contact(
            7, {"contact_id": 4, "relation": {"relationship_type": "兒子"}}
        )
        repository.update_owner_contact(
            7,
            9,
            {
                "contact": {"name": "王小明"},
                "relation": {"relationship_type": "兒子"},
            },
        )
        repository.deactivate_owner_contact(7, 9)
        repository.reactivate_owner_contact(7, 9)


if __name__ == "__main__":
    unittest.main()
