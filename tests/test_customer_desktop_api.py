import io
import json
import ssl
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet

from customer_desktop_api import (
    DesktopApiClient,
    DesktopApiConnectionError,
    DesktopApiRecordRepository,
    DesktopApiResponseError,
)
from customer_fields import LAND_FIELDS
from customer_security import encrypt_record, encrypt_value, make_fernet
import setup_local_https


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if self.payload is None:
            return b""
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class DesktopApiClientTests(unittest.TestCase):
    def setUp(self):
        self.requests = []

        def fake_urlopen(request, timeout):
            self.requests.append((request, timeout))
            path = urlparse(request.full_url)
            if path.path == "/health":
                return FakeResponse({"status": "ok", "backend": "postgresql"})
            if path.path == "/api/v1/auth/login":
                return FakeResponse(
                    {
                        "access_token": "test-token",
                        "user": {"id": 1, "username": "admin", "role": "admin"},
                    }
                )
            if path.path == "/api/v1/records" and request.method == "GET":
                offset = int(parse_qs(path.query).get("offset", [0])[0])
                rows = [{"id": 1}, {"id": 2}, {"id": 3}]
                return FakeResponse({"total": 3, "items": rows[offset : offset + 2]})
            if path.path == "/api/v1/records" and request.method == "POST":
                return FakeResponse({"id": 9})
            if path.path == "/api/v1/imports/records":
                return FakeResponse(
                    {
                        "batch_id": 12,
                        "inserted_count": 1,
                        "updated_count": 1,
                        "inserted_ids": [11],
                        "updated_ids": [9],
                    }
                )
            if path.path == "/api/v1/records/9" and request.method == "PUT":
                return FakeResponse({"id": 9})
            if path.path == "/api/v1/records/9/contact-logs":
                if request.method == "GET":
                    return FakeResponse({"items": [{"id": 5, "result": "完成"}]})
                if request.method == "POST":
                    return FakeResponse({"id": 5})
            if path.path == "/api/v1/records/9/contact-logs/5":
                return FakeResponse(None)
            if path.path == "/api/v1/records/9/follow-up":
                if request.method == "GET":
                    return FakeResponse(
                        {"item": {"due_date": "2026-07-20", "status": "待回覆"}}
                    )
                return FakeResponse(None)
            if path.path == "/api/v1/follow-ups":
                return FakeResponse({"items": [{"id": 9, "next_follow_up": "2026-07-20"}]})
            if path.path == "/api/v1/projects":
                if request.method == "GET":
                    return FakeResponse(
                        {"items": [{"id": 8, "title": "整合案", "customer_count": 2}]}
                    )
                return FakeResponse({"id": 8})
            if path.path == "/api/v1/projects/8":
                if request.method == "PUT":
                    return FakeResponse({"id": 8})
                return FakeResponse(None)
            if path.path == "/api/v1/projects/8/records":
                return FakeResponse({"processed": 2})
            if path.path == "/api/v1/tags":
                if request.method == "GET":
                    return FakeResponse({"items": [{"id": 4, "name": "優先"}]})
                if request.method == "POST":
                    return FakeResponse({"id": 4})
            if path.path == "/api/v1/tags/assignments":
                return FakeResponse({"processed": 2})
            if path.path == "/api/v1/tags/4":
                if request.method == "PUT":
                    return FakeResponse({"id": 4})
                return FakeResponse(None)
            if path.path == "/api/v1/records/9/tags":
                if request.method == "GET":
                    return FakeResponse({"tag_ids": [4], "items": [{"id": 4}]})
                return FakeResponse({"count": 1})
            if path.path == "/api/v1/records/9/attachments":
                if request.method == "GET":
                    return FakeResponse(
                        {"items": [{"id": 6, "status": "external"}]}
                    )
                return FakeResponse({"id": 6})
            if path.path == "/api/v1/records/9/attachments/upload":
                return FakeResponse({"id": 7})
            if path.path in {
                "/api/v1/records/9/attachments/6",
                "/api/v1/records/9/attachments/7",
            }:
                return FakeResponse(None)
            if path.path in {"/api/v1/records/9", "/api/v1/auth/logout"}:
                return FakeResponse(None)
            raise AssertionError((request.method, request.full_url))

        self.client = DesktopApiClient(urlopen_fn=fake_urlopen)

    def test_login_pagination_crud_and_logout(self):
        self.assertEqual(self.client.health()["backend"], "postgresql")
        self.assertEqual(self.client.login("admin", "secret")["role"], "admin")
        self.assertEqual(
            [row["id"] for row in self.client.list_all_records(page_size=2)],
            [1, 2, 3],
        )
        self.assertEqual(self.client.create_record({"district": "桃園區"}), 9)
        self.assertEqual(
            self.client.replace_record(9, {"district": "中壢區"}), 9
        )
        self.assertEqual(self.client.list_contact_logs(9)[0]["id"], 5)
        self.assertEqual(
            self.client.add_contact_log(9, {"result": "完成"}), 5
        )
        self.assertTrue(self.client.delete_contact_log(9, 5))
        self.assertEqual(self.client.get_follow_up(9)["status"], "待回覆")
        self.assertTrue(
            self.client.save_follow_up(
                9, {"due_date": "2026-07-20", "status": "待回覆"}
            )
        )
        self.assertTrue(self.client.delete_follow_up(9))
        self.assertEqual(self.client.list_follow_ups()[0]["id"], 9)
        self.assertEqual(self.client.list_projects()[0]["id"], 8)
        self.assertEqual(self.client.save_project("整合案", "進行中", ""), 8)
        self.assertEqual(
            self.client.save_project("整合案二期", "議價中", "更新", 8), 8
        )
        self.assertEqual(self.client.update_project_records(8, [9, 10], "add"), 2)
        self.assertTrue(self.client.delete_project(8))
        self.assertEqual(self.client.list_tags()[0]["id"], 4)
        self.assertEqual(self.client.save_tag("優先", "#ff8800"), 4)
        self.assertEqual(self.client.save_tag("重要", "#0088ff", 4), 4)
        self.assertEqual(self.client.get_record_tag_ids(9), {4})
        self.assertEqual(self.client.set_record_tags(9, [4, 4]), 1)
        self.assertEqual(self.client.set_records_tags([9, 10], [4], "add"), 2)
        self.assertTrue(self.client.delete_tag(4))
        self.assertEqual(self.client.list_attachments(9)[0]["id"], 6)
        self.assertEqual(
            self.client.add_external_attachment(9, "C:/docs/a.pdf", "謄本"), 6
        )
        with tempfile.TemporaryDirectory() as temporary:
            attachment_path = Path(temporary) / "proof.txt"
            attachment_path.write_text("proof", encoding="utf-8")
            self.assertEqual(
                self.client.upload_managed_attachment(9, attachment_path, "納管"),
                7,
            )
        self.assertTrue(self.client.delete_attachment(9, 7))
        import_result = self.client.import_records(
            [
                {"record_id": None, "values": {"district": "桃園區"}},
                {"record_id": 9, "values": {"district": "中壢區"}},
            ],
            "地主清冊.xlsx",
        )
        self.assertEqual(import_result["batch_id"], 12)
        self.assertEqual(import_result["inserted_ids"], [11])
        self.assertTrue(self.client.delete_record(9))
        authenticated_requests = [
            request for request, _timeout in self.requests
            if "/auth/login" not in request.full_url and "/health" not in request.full_url
        ]
        self.assertTrue(
            all(request.get_header("Authorization") == "Bearer test-token" for request in authenticated_requests)
        )
        self.client.logout()
        self.assertFalse(self.client.authenticated)

    def test_rejects_plain_http_for_non_loopback_hosts(self):
        with self.assertRaises(ValueError):
            DesktopApiClient("http://192.168.1.20:8732")
        client = DesktopApiClient(
            "http://192.168.1.20:8732", allow_insecure_lan=True
        )
        self.assertEqual(client.base_url, "http://192.168.1.20:8732")

    def test_https_client_uses_configured_private_ca(self):
        with tempfile.TemporaryDirectory() as temporary:
            setup_local_https.create_local_https_certificate(temporary)
            ca_path = setup_local_https.certificate_paths(temporary).ca_certificate_pem
            captured = {}

            def fake_https_urlopen(request, timeout, context):
                captured.update(request=request, timeout=timeout, context=context)
                return FakeResponse({"status": "ok", "backend": "postgresql"})

            client = DesktopApiClient(
                "https://127.0.0.1:8732",
                ca_certificate=ca_path,
                urlopen_fn=fake_https_urlopen,
            )
            self.assertEqual(client.health()["backend"], "postgresql")
            self.assertIs(captured["context"], client._ssl_context)

    def test_http_errors_are_translated_and_clear_expired_login(self):
        def unauthorized(request, timeout):
            del request, timeout
            raise HTTPError(
                "http://127.0.0.1:8732/api/v1/records",
                401,
                "Unauthorized",
                {},
                io.BytesIO(json.dumps({"detail": "登入已失效"}).encode("utf-8")),
            )

        client = DesktopApiClient(urlopen_fn=unauthorized)
        client.access_token = "expired"
        with self.assertRaises(DesktopApiResponseError) as caught:
            client.list_records()
        self.assertEqual(caught.exception.status_code, 401)
        self.assertIn("登入已失效", str(caught.exception))
        self.assertFalse(client.authenticated)

        def validation_error(request, timeout):
            del request, timeout
            raise HTTPError(
                "http://127.0.0.1:8732/api/v1/imports/records",
                422,
                "Unprocessable Entity",
                {},
                io.BytesIO(
                    json.dumps(
                        {
                            "detail": [
                                {
                                    "loc": ["body", "items", 0, "values", "_duplicate_reason"],
                                    "msg": "Extra inputs are not permitted",
                                    "type": "extra_forbidden",
                                },
                                {
                                    "loc": ["body", "items", 1, "values", "_duplicate_reason"],
                                    "msg": "Extra inputs are not permitted",
                                    "type": "extra_forbidden",
                                },
                            ]
                        }
                    ).encode("utf-8")
                ),
            )

        validation_client = DesktopApiClient(urlopen_fn=validation_error)
        validation_client.access_token = "test-token"
        with self.assertRaises(DesktopApiResponseError) as validation_caught:
            validation_client.import_records(
                [{"record_id": None, "values": {"_duplicate_reason": "重複"}}]
            )
        self.assertIn("系統不支援的欄位", str(validation_caught.exception))
        self.assertEqual(str(validation_caught.exception).count("_duplicate_reason"), 1)

    def test_safe_get_retries_once_after_transient_network_failure(self):
        attempts = []
        sleeps = []

        def transient_then_success(request, timeout):
            del request, timeout
            attempts.append(1)
            if len(attempts) == 1:
                raise URLError(TimeoutError("timed out"))
            return FakeResponse({"status": "ok", "backend": "postgresql"})

        client = DesktopApiClient(
            urlopen_fn=transient_then_success,
            retry_delay_seconds=0.1,
            sleep_fn=sleeps.append,
        )
        self.assertEqual(client.health()["status"], "ok")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sleeps, [0.1])

    def test_write_request_is_not_retried_when_connection_fails(self):
        attempts = []

        def unavailable(request, timeout):
            del request, timeout
            attempts.append(1)
            raise URLError(ConnectionRefusedError("connection refused"))

        client = DesktopApiClient(
            urlopen_fn=unavailable,
            retry_delay_seconds=0,
        )
        with self.assertRaises(DesktopApiConnectionError) as caught:
            client.login("admin", "password")
        self.assertEqual(len(attempts), 1)
        self.assertIn("尚未啟動", str(caught.exception))

    def test_certificate_failure_is_clear_and_not_retried(self):
        attempts = []

        def invalid_certificate(request, timeout):
            del request, timeout
            attempts.append(1)
            raise URLError(
                ssl.SSLCertVerificationError(1, "certificate verify failed")
            )

        client = DesktopApiClient(urlopen_fn=invalid_certificate)
        with self.assertRaises(DesktopApiConnectionError) as caught:
            client.health()
        self.assertEqual(len(attempts), 1)
        self.assertIn("最新公司筆電客戶端包", str(caught.exception))

    def test_remote_maintenance_client_uses_server_endpoints(self):
        requests = []

        def remote_maintenance(request, timeout):
            requests.append((request.method, urlparse(request.full_url).path, timeout))
            path = urlparse(request.full_url).path
            if path == "/api/v1/maintenance/encrypt-existing-records":
                return FakeResponse({"updated_records": 2})
            if path == "/api/v1/server-backups":
                return FakeResponse({"items": [{"name": "server.zip", "status": "ok"}]})
            if path == "/api/v1/server-backups/restore":
                return FakeResponse({"status": "ok", "restored_backup": "server.zip"})
            if path == "/api/v1/server-backup-targets":
                if request.method == "GET":
                    return FakeResponse({"items": [{"id": 4, "name": "NAS"}]})
                return FakeResponse({"id": 4})
            if path == "/api/v1/server-backup-targets/4":
                if request.method == "DELETE":
                    return FakeResponse({"deleted": True})
                return FakeResponse({"id": 4})
            if path == "/api/v1/server-backup-targets/sync":
                return FakeResponse({"status": "ok", "results": []})
            raise AssertionError((request.method, request.full_url))

        client = DesktopApiClient(urlopen_fn=remote_maintenance)
        client.access_token = "test-token"
        self.assertEqual(client.encrypt_existing_records()["updated_records"], 2)
        self.assertEqual(client.list_server_backups()[0]["name"], "server.zip")
        self.assertEqual(
            client.restore_server_backup("server.zip", "還原家中伺服器")[
                "restored_backup"
            ],
            "server.zip",
        )
        self.assertEqual(client.list_server_backup_targets()[0]["id"], 4)
        self.assertEqual(
            client.save_server_backup_target("NAS", r"\\NAS\backup"), 4
        )
        self.assertEqual(
            client.save_server_backup_target(
                "NAS", r"\\NAS\backup", target_id=4
            ),
            4,
        )
        self.assertTrue(client.delete_server_backup_target(4))
        self.assertEqual(client.sync_server_backup_targets()["status"], "ok")
        self.assertIn(
            ("POST", "/api/v1/server-backups/restore", 30 * 60), requests
        )


class FakeRecordClient:
    def __init__(self):
        self.rows = [self.record(2, "王大明"), self.record(1, "李小華")]
        self.created = []
        self.replaced = []
        self.deleted = []
        self.contact_logs = []
        self.contact_created = []
        self.contact_deleted = []
        self.reminder = None
        self.follow_up_saved = []
        self.follow_up_deleted = []
        self.tags = [{"id": 4, "name": "優先", "color": "#ff8800", "customer_count": 0}]
        self.record_tag_ids = {1: set(), 2: set()}
        self.tag_saved = []
        self.tag_deleted = []
        self.bulk_tag_updates = []
        self.attachments = []
        self.external_attachments = []
        self.managed_attachments = []
        self.deleted_attachments = []
        self.projects = [
            {"id": 8, "title": "整合案", "status": "進行中", "customer_count": 0}
        ]
        self.project_saved = []
        self.project_deleted = []
        self.project_record_updates = []
        self.imported_batches = []
        self.change_logs = []
        self.custom_fields = [{"id": 3, "field_key": "stage", "label": "開發階段"}]
        self.custom_values = {2: {3: "初談"}}
        self.text_templates = [
            {"id": 10, "template_type": "note", "title": "電話", "content": "已電話聯絡"}
        ]
        self.watchlist = [{"id": 1, "name": "王大明", "note": "先電話聯絡"}]
        self.operation_logs = []
        self.locations = []
        self.duplicate_pairs = set()

    @staticmethod
    def record(record_id, owner_name):
        row = {key: "" for key, _label in LAND_FIELDS}
        row.update(
            {
                "id": record_id,
                "district": "桃園區",
                "section": "測試段",
                "land_number": str(record_id),
                "owner_name": owner_name,
                "case_names": "",
                "tag_names": "",
                "attachment_count": 0,
                "attachment_names": "",
                "custom_values": "",
                "last_contact": "",
                "next_follow_up": "",
                "follow_up_status": "",
            }
        )
        return row

    def list_all_records(self):
        return list(self.rows)

    def create_record(self, values):
        self.created.append(dict(values))
        return 3

    def replace_record(self, record_id, values):
        self.replaced.append((record_id, dict(values)))
        return record_id

    def delete_record(self, record_id):
        self.deleted.append(record_id)

    def import_records(self, items, source_file_name="import.xlsx"):
        self.imported_batches.append((list(items), source_file_name))
        inserted_ids = [11 for item in items if item.get("record_id") is None]
        updated_ids = [
            int(item["record_id"])
            for item in items
            if item.get("record_id") is not None
        ]
        return {
            "batch_id": 12,
            "inserted_count": len(inserted_ids),
            "updated_count": len(updated_ids),
            "inserted_ids": inserted_ids,
            "updated_ids": updated_ids,
        }

    def list_contact_logs(self, record_id):
        return [
            row for row in self.contact_logs if row["customer_id"] == int(record_id)
        ]

    def add_contact_log(self, record_id, values):
        self.contact_created.append((int(record_id), dict(values)))
        row = {"id": 7, "customer_id": int(record_id), **dict(values)}
        self.contact_logs.append(row)
        return 7

    def delete_contact_log(self, record_id, log_id):
        self.contact_deleted.append((int(record_id), int(log_id)))
        self.contact_logs = [
            row for row in self.contact_logs if int(row["id"]) != int(log_id)
        ]
        return True

    def get_follow_up(self, record_id):
        del record_id
        return dict(self.reminder) if self.reminder is not None else None

    def save_follow_up(self, record_id, values):
        self.follow_up_saved.append((int(record_id), dict(values)))
        self.reminder = {"customer_id": int(record_id), **dict(values)}
        return True

    def delete_follow_up(self, record_id):
        self.follow_up_deleted.append(int(record_id))
        self.reminder = None
        return True

    def list_follow_ups(self, limit=500):
        del limit
        if self.reminder is None:
            return []
        return [
            {
                "id": self.reminder["customer_id"],
                "next_follow_up": self.reminder.get("due_date") or "",
                "follow_up_status": self.reminder.get("status") or "",
            }
        ]

    def list_tags(self):
        return [dict(tag) for tag in self.tags]

    def list_projects(self):
        return [dict(project) for project in self.projects]

    def save_project(self, title, status="進行中", note="", project_id=None):
        self.project_saved.append((title, status, note, project_id))
        return int(project_id or 8)

    def delete_project(self, project_id):
        self.project_deleted.append(int(project_id))
        return True

    def update_project_records(self, project_id, record_ids, mode="add"):
        ids = sorted({int(record_id) for record_id in record_ids})
        self.project_record_updates.append((int(project_id), ids, mode))
        return len(ids)

    def save_tag(self, name, color="", tag_id=None):
        saved_id = int(tag_id or 5)
        self.tag_saved.append((name, color, tag_id))
        return saved_id

    def delete_tag(self, tag_id):
        self.tag_deleted.append(int(tag_id))
        return True

    def get_record_tag_ids(self, record_id):
        return set(self.record_tag_ids.get(int(record_id), set()))

    def set_record_tags(self, record_id, tag_ids):
        values = {int(tag_id) for tag_id in tag_ids}
        self.record_tag_ids[int(record_id)] = values
        return len(values)

    def set_records_tags(self, record_ids, tag_ids, mode="add"):
        record_ids = [int(record_id) for record_id in record_ids]
        tag_ids = {int(tag_id) for tag_id in tag_ids}
        self.bulk_tag_updates.append((record_ids, tag_ids, mode))
        for record_id in record_ids:
            current = self.record_tag_ids.setdefault(record_id, set())
            if mode == "replace":
                self.record_tag_ids[record_id] = set(tag_ids)
            elif mode == "remove":
                current.difference_update(tag_ids)
            else:
                current.update(tag_ids)
        return len(record_ids)

    def list_attachments(self, record_id):
        return [
            dict(row)
            for row in self.attachments
            if int(row["customer_id"]) == int(record_id)
        ]

    def add_external_attachment(self, record_id, file_path, description=""):
        self.external_attachments.append(
            (int(record_id), str(file_path), str(description))
        )
        self.attachments.append(
            {
                "id": 6,
                "customer_id": int(record_id),
                "file_path": str(file_path),
                "description": str(description),
                "status": "external",
            }
        )
        return 6

    def upload_managed_attachment(self, record_id, file_path, description=""):
        self.managed_attachments.append(
            (int(record_id), str(file_path), str(description))
        )
        self.attachments.append(
            {
                "id": 7,
                "customer_id": int(record_id),
                "file_path": str(file_path),
                "description": str(description),
                "status": "managed",
            }
        )
        return 7

    def delete_attachment(self, record_id, attachment_id):
        self.deleted_attachments.append((int(record_id), int(attachment_id)))
        self.attachments = [
            row for row in self.attachments if int(row["id"]) != int(attachment_id)
        ]
        return True

    def list_record_change_logs(self, record_id, limit=300):
        return [
            dict(row)
            for row in self.change_logs
            if int(row["record_id"]) == int(record_id)
        ][:limit]

    def add_record_change_logs(self, items):
        self.change_logs.extend(dict(item) for item in items)
        return len(items)

    def list_custom_fields(self):
        return [dict(row) for row in self.custom_fields]

    def save_custom_field(self, label, field_key=None, field_id=None):
        saved_id = int(field_id or 4)
        self.custom_fields.append(
            {"id": saved_id, "field_key": field_key or "field", "label": label}
        )
        return saved_id

    def delete_custom_field(self, field_id):
        self.custom_fields = [
            row for row in self.custom_fields if int(row["id"]) != int(field_id)
        ]
        return True

    def get_record_custom_values(self, record_id):
        return dict(self.custom_values.get(int(record_id), {}))

    def set_record_custom_values(self, record_id, values):
        self.custom_values[int(record_id)] = {
            int(field_id): value for field_id, value in dict(values).items()
        }
        return len(values)

    def set_records_custom_values(self, record_ids, values):
        for record_id in record_ids:
            self.set_record_custom_values(record_id, values)
        return len(set(record_ids))

    def list_text_templates(self, template_type=None):
        return [
            dict(row)
            for row in self.text_templates
            if template_type is None or row["template_type"] == template_type
        ]

    def save_text_template(self, title, content, template_type="note", template_id=None):
        saved_id = int(template_id or 11)
        self.text_templates.append(
            {
                "id": saved_id,
                "template_type": template_type,
                "title": title,
                "content": content,
            }
        )
        return saved_id

    def delete_text_template(self, template_id):
        self.text_templates = [
            row for row in self.text_templates if int(row["id"]) != int(template_id)
        ]
        return True

    def list_watchlist(self):
        return [dict(row) for row in self.watchlist]

    def replace_watchlist(self, items):
        self.watchlist = [dict(item) for item in items]
        return len(self.watchlist)

    def list_operation_logs(self, limit=300):
        return [dict(row) for row in self.operation_logs[:limit]]

    def add_operation_log(self, action_type, summary, detail=""):
        self.operation_logs.insert(
            0,
            {
                "id": len(self.operation_logs) + 1,
                "action_type": action_type,
                "summary": summary,
                "detail": detail,
            },
        )
        return self.operation_logs[0]["id"]

    def list_record_locations(self):
        return [dict(row) for row in self.locations]

    def set_record_location(self, record_id, latitude, longitude, source="manual"):
        self.locations.append(
            {
                "id": len(self.locations) + 1,
                "customer_id": int(record_id),
                "latitude": float(latitude),
                "longitude": float(longitude),
                "source": source,
            }
        )
        return self.locations[-1]["id"]

    def ignored_duplicate_pairs(self):
        return set(self.duplicate_pairs)

    def ignore_duplicate_pair(self, left_record_id, right_record_id):
        self.duplicate_pairs.add(
            tuple(sorted((int(left_record_id), int(right_record_id))))
        )
        return True

    def verify_managed_attachments(self):
        return [{"id": 7, "status": "managed", "integrity_status": "正常"}]


class DesktopApiRecordRepositoryTests(unittest.TestCase):
    def test_record_adapter_pages_decrypts_writes_and_invalidates(self):
        client = FakeRecordClient()
        fernet = make_fernet(Fernet.generate_key())
        repository = DesktopApiRecordRepository(client, fernet)
        self.assertEqual(repository.count_customers(), 2)
        self.assertEqual(repository.fetch_customer_ids(), {1, 2})
        self.assertEqual(repository.fetch_customer_page(1)[0]["id"], 2)
        self.assertEqual(repository.fetch_customer_page(2, before_id=2)[0]["id"], 1)

        values = {key: "" for key, _label in LAND_FIELDS}
        values.update(
            {
                "district": "中壢區",
                "section": "青埔段",
                "land_number": "200",
                "owner_name": "陳先生",
                "address": "測試地址",
            }
        )
        encrypted = encrypt_record(fernet, values)
        self.assertEqual(repository.save_customer(encrypted), 3)
        self.assertEqual(client.created[0]["owner_name"], "陳先生")
        self.assertEqual(client.created[0]["address"], "測試地址")
        self.assertEqual(repository.update_customers([{**encrypted, "id": 2}]), 1)
        self.assertEqual(client.replaced[0][0], 2)
        self.assertEqual(repository.delete_customers([2, 1, 2]), 2)
        self.assertEqual(client.deleted, [1, 2])

        import_result = repository.import_records(
            [{**encrypted, "_duplicate_reason": "資料庫已存在", "_row_number": 2}],
            [{**encrypted, "id": 2}],
            "地主清冊.xlsx",
        )
        self.assertEqual(import_result["batch_id"], 12)
        self.assertEqual(repository.last_inserted_customer_ids, [11])
        imported_items, source_name = client.imported_batches[0]
        self.assertEqual(source_name, "地主清冊.xlsx")
        self.assertEqual(imported_items[0]["values"]["owner_name"], "陳先生")
        self.assertNotIn("_duplicate_reason", imported_items[0]["values"])
        self.assertNotIn("_row_number", imported_items[0]["values"])
        self.assertEqual(imported_items[1]["record_id"], 2)

        encrypted_contact_note = encrypt_value(fernet, "現場拜訪")
        self.assertEqual(
            repository.add_contact_log(
                2,
                "2026-07-14",
                "面談",
                "願意再談",
                "2026-07-20",
                encrypted_contact_note,
            ),
            7,
        )
        self.assertEqual(client.contact_created[0][1]["note"], "現場拜訪")
        self.assertEqual(repository.list_contact_logs(2)[0]["id"], 7)
        self.assertEqual(repository.delete_contact_log(7), 1)
        self.assertEqual(client.contact_deleted, [(2, 7)])

        repository.save_follow_up_reminder(
            2,
            "2026-07-21",
            "待回覆",
            encrypt_value(fernet, "下週再聯絡"),
        )
        self.assertEqual(client.follow_up_saved[0][1]["note"], "下週再聯絡")
        self.assertEqual(
            repository.get_follow_up_reminder(2)["status"], "待回覆"
        )
        self.assertEqual(repository.list_follow_up_reminders()[0]["customer_id"], 2)
        self.assertEqual(repository.delete_follow_up_reminder(2), 1)
        self.assertEqual(client.follow_up_deleted, [2])

        self.assertEqual(repository.list_cases()[0]["title"], "整合案")
        self.assertEqual(repository.save_case("整合案二期", "議價中", "更新"), 8)
        self.assertEqual(
            client.project_saved[0], ("整合案二期", "議價中", "更新", None)
        )
        self.assertEqual(repository.add_customers_to_case(8, [2, 1, 2]), 2)
        self.assertEqual(repository.remove_customers_from_case(8, [1]), 1)
        self.assertEqual(
            client.project_record_updates,
            [(8, [1, 2], "add"), (8, [1], "remove")],
        )
        self.assertEqual(repository.delete_case(8), 1)
        self.assertEqual(client.project_deleted, [8])

        self.assertEqual(repository.list_tags()[0]["name"], "優先")
        self.assertEqual(repository.save_tag("重要", "#0088ff"), 5)
        self.assertEqual(client.tag_saved[0], ("重要", "#0088ff", None))
        self.assertEqual(repository.set_customer_tags(2, [4, 4]), 1)
        self.assertEqual(repository.get_customer_tag_ids(2), {4})
        self.assertEqual(
            repository.set_customers_tags([1, 2], [4], "replace"), 2
        )
        self.assertEqual(client.bulk_tag_updates[0], ([1, 2], {4}, "replace"))
        self.assertEqual(repository.delete_tag(4), 1)
        self.assertEqual(client.tag_deleted, [4])

        self.assertEqual(
            repository.add_customer_attachment(2, "C:/docs/a.pdf", "外部"), 6
        )
        with tempfile.TemporaryDirectory() as temporary:
            attachment_path = Path(temporary) / "managed.txt"
            attachment_path.write_text("managed", encoding="utf-8")
            self.assertEqual(
                repository.import_managed_attachment(
                    2, attachment_path, Path(temporary) / "ignored", "納管"
                ),
                7,
            )
        self.assertEqual(len(repository.list_customer_attachments(2)), 2)
        self.assertEqual(repository.delete_customer_attachment(7), 1)
        self.assertEqual(client.deleted_attachments, [(2, 7)])
        self.assertEqual(repository.data_revision, 19)

    def test_record_adapter_supports_remote_desktop_productivity_features(self):
        client = FakeRecordClient()
        repository = DesktopApiRecordRepository(
            client, make_fernet(Fernet.generate_key())
        )

        self.assertEqual(repository.list_custom_fields()[0]["label"], "開發階段")
        self.assertEqual(repository.save_custom_field("意願", "intent"), 4)
        self.assertEqual(repository.get_customer_custom_values(2), {3: "初談"})
        self.assertEqual(repository.set_customer_custom_values(2, {3: "有意願"}), 1)
        self.assertEqual(repository.set_customers_custom_values([1, 2], {3: "追蹤"}), 2)
        self.assertEqual(repository.list_text_templates("note")[0]["id"], 10)
        self.assertEqual(repository.save_text_template("拜訪", "已拜訪"), 11)
        self.assertEqual(repository.get_watchlist_entries()[0]["name"], "王大明")
        self.assertEqual(repository.replace_watchlist_entries([{"name": "李小華", "note": ""}]), 1)
        self.assertEqual(repository.find_watchlist_match(" 李 小 華 ")["name"], "李小華")

        self.assertEqual(
            repository.add_record_change_logs(
                [
                    {
                        "record_id": 2,
                        "action_type": "修改資料",
                        "field_key": "note",
                        "field_label": "備註",
                        "old_value": "",
                        "new_value": "完成",
                    }
                ]
            ),
            1,
        )
        self.assertEqual(repository.get_record_change_logs(2)[0]["new_value"], "完成")
        self.assertEqual(repository.log_operation("測試", "完成", "桌面 API"), 1)
        self.assertEqual(repository.get_operation_logs()[0]["summary"], "完成")
        self.assertEqual(repository.set_customer_location(2, 24.99, 121.31), 1)
        self.assertEqual(repository.list_customer_locations()[0]["customer_id"], 2)
        self.assertEqual(repository.ignore_duplicate_pair(2, 1), 1)
        self.assertEqual(repository.ignored_duplicate_pairs(), {(1, 2)})
        self.assertEqual(repository.verify_managed_attachments()[0]["integrity_status"], "正常")
        self.assertEqual(repository.delete_custom_field(4), 1)
        self.assertEqual(repository.delete_text_template(11), 1)


if __name__ == "__main__":
    unittest.main()
