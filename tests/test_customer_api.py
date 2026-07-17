import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient

from customer_api.app import create_app
from customer_api.auth import LoginThrottle, SessionStore
from customer_api.config import ApiSettings
from customer_api.data_sources import SQLiteCustomerDataSource, _filter_records
from customer_api.local_postgres import load_postgres_dsn, save_postgres_dsn
from customer_fields import LAND_FIELDS
from customer_security import encrypt_record, make_fernet
from migrate_sqlite_to_postgresql import (
    DEVICE_LOCAL_TABLES,
    EXTENDED_SOURCE_TABLES,
    _json_for_postgres,
    analyze_records,
    collect_source_counts,
    land_key_for,
    owner_key_for,
)


class CustomerApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        project_root = Path(__file__).resolve().parents[1]
        self.settings = ApiSettings(
            backend="sqlite",
            sqlite_database_path=self.root / "customers.db",
            backup_directory=self.root / "backups",
            attachment_directory=self.root / "attachments",
            schema_path=project_root / "schema.sql",
            seed_path=self.root / "missing-seed.sql",
            session_ttl_seconds=3600,
            max_page_size=100,
        )
        self.source = SQLiteCustomerDataSource(self.settings)
        self.source.repository.create_admin_user("admin-password")
        self.data_key = self.source.repository.authenticate_user("admin", "admin-password")
        self.fernet = make_fernet(self.data_key)
        self.record_id = self.source.repository.save_customer(
            encrypt_record(
                self.fernet,
                self.record(
                    district="桃園區",
                    section="中正段",
                    registration_order="15",
                    land_number="100-1",
                    area="1000",
                    declared_value="50000",
                    numerator="1",
                    denominator="2",
                    ping="151.25",
                    total_declared_value="25000000",
                    owner_name="王大明",
                    external_id="H100059743",
                    address="桃園市測試路1號",
                ),
            )
        )
        self.source.repository.create_user(
            "viewer", "viewer-password", "viewer", self.data_key, "檢視帳號"
        )
        self.app = create_app(settings=self.settings, data_source=self.source)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temp_context.cleanup()

    @staticmethod
    def record(**values):
        record = {key: "" for key, _label in LAND_FIELDS}
        record.update(values)
        record["name"] = record.get("owner_name") or ""
        return record

    def login(self, username="admin", password="admin-password"):
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_api_filter_allows_or_values_within_one_field(self):
        records = [
            {"district": "桃園區", "section": "中路"},
            {"district": "桃園區", "section": "中路段"},
            {"district": "中壢區", "section": "中路"},
        ]

        self.assertEqual(
            _filter_records(
                records,
                filters={"district": "桃園區", "section": "中路、中路段"},
            ),
            records[:2],
        )

    def test_health_login_query_owner_and_land_views(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["backend"], "sqlite")
        self.assertEqual(health.json()["schema_version"], 7)

        bad_login = self.client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(bad_login.status_code, 401)

        headers = self.login()
        response = self.client.get(
            "/api/v1/records", params={"q": "王大明"}, headers=headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["external_id"], "H100059743")

        owners = self.client.get("/api/v1/owners", headers=headers).json()
        self.assertEqual(owners["total"], 1)
        self.assertEqual(owners["items"][0]["land_count"], 1)
        self.assertEqual(owners["items"][0]["total_ping"], "151.25")

        lands = self.client.get("/api/v1/lands", headers=headers).json()
        self.assertEqual(lands["total"], 1)
        self.assertEqual(lands["items"][0]["land_number"], "100-1")
        self.assertEqual(lands["items"][0]["owners"][0]["name"], "王大明")

    def test_mobile_pwa_is_served_with_security_headers(self):
        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.json()["mobile"], "/mobile/")

        page = self.client.get("/mobile/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("地主開發助手", page.text)
        self.assertIn("default-src 'self'", page.headers["content-security-policy"])
        self.assertEqual(page.headers["cache-control"], "no-store")

        manifest = self.client.get("/mobile/manifest.webmanifest")
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()["start_url"], "/mobile/")

        service_worker = self.client.get("/mobile/service-worker.js")
        self.assertEqual(service_worker.status_code, 200)
        self.assertIn('url.pathname.startsWith("/api/")', service_worker.text)
        self.assertIn("no-store", service_worker.headers["cache-control"])

    def test_full_desktop_remote_workflow_end_to_end(self):
        headers = self.login()

        project = self.client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "title": "中正段開發案",
                "status": "進行中",
                "note": "測試",
                "assigned_to": "王業務",
                "due_date": "2026-07-17",
                "priority": "高",
                "next_action": "電話聯絡",
                "archived": False,
            },
        )
        self.assertEqual(project.status_code, 201, project.text)
        project_id = project.json()["id"]
        task = self.client.post(
            "/api/v1/project-tasks",
            headers=headers,
            json={
                "project_id": project_id,
                "title": "確認持分",
                "assignee": "王業務",
                "due_date": "2026-07-17",
                "status": "待處理",
                "priority": "緊急",
                "checklist": "核對謄本",
            },
        )
        self.assertEqual(task.status_code, 201, task.text)
        tasks = self.client.get("/api/v1/project-tasks", headers=headers)
        self.assertEqual(tasks.json()["items"][0]["title"], "確認持分")

        refreshed = self.client.post(
            "/api/v1/notifications/refresh", headers=headers, json={}
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        notifications = self.client.get("/api/v1/notifications", headers=headers)
        self.assertGreaterEqual(len(notifications.json()["items"]), 1)
        notification_id = notifications.json()["items"][0]["id"]
        marked = self.client.put(
            "/api/v1/notifications",
            headers=headers,
            json={"notification_ids": [notification_id], "action": "read"},
        )
        self.assertEqual(marked.json()["count"], 1)

        created_user = self.client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "username": "editor2",
                "password": "editor2-password",
                "role": "editor",
                "display_name": "第二位編輯者",
            },
        )
        self.assertEqual(created_user.status_code, 201, created_user.text)
        user_id = created_user.json()["id"]
        updated_user = self.client.put(
            f"/api/v1/users/{user_id}",
            headers=headers,
            json={"display_name": "編輯者二號", "role": "viewer", "active": True},
        )
        self.assertEqual(updated_user.status_code, 200, updated_user.text)
        reset = self.client.put(
            f"/api/v1/users/{user_id}/password",
            headers=headers,
            json={"new_password": "editor2-new-password"},
        )
        self.assertEqual(reset.status_code, 200, reset.text)

        undo = self.client.post(
            "/api/v1/undo-operations/snapshot",
            headers=headers,
            json={
                "operation_type": "批次修改",
                "ids": [self.record_id],
                "summary": "修改前快照",
            },
        )
        self.assertEqual(undo.status_code, 201, undo.text)
        original = self.client.get(
            f"/api/v1/records/{self.record_id}", headers=headers
        ).json()
        changed = dict(original)
        changed["district"] = "中壢區"
        for key in list(changed):
            if key not in {field_key for field_key, _label in LAND_FIELDS}:
                changed.pop(key)
        self.assertEqual(
            self.client.put(
                f"/api/v1/records/{self.record_id}", headers=headers, json=changed
            ).status_code,
            200,
        )
        applied = self.client.post(
            f"/api/v1/undo-operations/{undo.json()['id']}/apply",
            headers=headers,
            json={},
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        restored = self.client.get(
            f"/api/v1/records/{self.record_id}", headers=headers
        ).json()
        self.assertEqual(restored["district"], "桃園區")

        self.assertEqual(
            self.client.delete(
                f"/api/v1/records/{self.record_id}", headers=headers
            ).status_code,
            204,
        )
        recycled = self.client.get("/api/v1/recycle-bin", headers=headers).json()
        recycle_id = recycled["items"][0]["id"]
        recycle_restore = self.client.post(
            "/api/v1/recycle-bin/restore",
            headers=headers,
            json={"ids": [recycle_id]},
        )
        self.assertEqual(recycle_restore.status_code, 200, recycle_restore.text)
        self.assertIn(self.record_id, recycle_restore.json()["record_ids"])

        password_change = self.client.put(
            "/api/v1/auth/password",
            headers=headers,
            json={
                "current_password": "admin-password",
                "new_password": "admin-new-password",
            },
        )
        self.assertEqual(password_change.status_code, 200, password_change.text)
        self.login("admin", "admin-new-password")

    def test_server_backup_controls_are_admin_only_and_use_server_backup_module(self):
        headers = self.login()
        with patch(
            "backup_postgresql.backup_status",
            return_value={
                "status": "ok",
                "backup_directory": "C:/server-backups",
                "backup_count": 2,
                "latest_backup": "C:/server-backups/latest.zip",
                "latest_backup_at": "2026-07-17T08:00:00+00:00",
                "total_bytes": 1234,
            },
        ), patch(
            "backup_postgresql.create_backup",
            return_value={"status": "ok", "backup_path": "C:/server-backups/new.zip"},
        ) as create_backup, patch(
            "backup_postgresql.prune_backups", return_value=[]
        ):
            status = self.client.get(
                "/api/v1/server-backups/status", headers=headers
            )
            self.assertEqual(status.status_code, 200, status.text)
            self.assertEqual(status.json()["backup_count"], 2)
            created = self.client.post(
                "/api/v1/server-backups",
                headers=headers,
                json={"label": "manual", "retention_days": 60, "max_count": 20},
            )
            self.assertEqual(created.status_code, 201, created.text)
            create_backup.assert_called_once_with(
                label="manual", retention_days=60, max_count=20
            )
            maintained = self.client.post(
                "/api/v1/server-backups/maintenance",
                headers=headers,
                json={"retention_days": 60, "max_count": 20},
            )
            self.assertEqual(maintained.status_code, 200, maintained.text)

        viewer_headers = self.login("viewer", "viewer-password")
        forbidden = self.client.get(
            "/api/v1/server-backups/status", headers=viewer_headers
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_remote_encrypt_existing_records_encrypts_plaintext_and_is_admin_only(self):
        plaintext_id = self.source.repository.save_customer(
            self.record(
                district="中壢區",
                section="青埔段",
                land_number="200-1",
                owner_name="尚未加密地主",
                external_id="A123456789",
                address="測試地址",
                note="明文備註",
            )
        )
        headers = self.login()
        response = self.client.post(
            "/api/v1/maintenance/encrypt-existing-records",
            headers=headers,
            json={},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["updated_records"], 1)
        with self.source.database.connect() as conn:
            stored = conn.execute(
                "SELECT owner_name, external_id, address, note FROM customers WHERE id=?",
                (plaintext_id,),
            ).fetchone()
        self.assertTrue(all(str(value).startswith("enc:v1:") for value in stored))

        viewer_headers = self.login("viewer", "viewer-password")
        denied = self.client.post(
            "/api/v1/maintenance/encrypt-existing-records",
            headers=viewer_headers,
            json={},
        )
        self.assertEqual(denied.status_code, 403)

    def test_server_backup_target_crud_uses_paths_on_the_server(self):
        headers = self.login()
        destination = self.root / "offsite"
        destination.mkdir()
        created = self.client.post(
            "/api/v1/server-backup-targets",
            headers=headers,
            json={
                "name": "測試外接碟",
                "directory_path": str(destination),
                "enabled": True,
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        target_id = created.json()["id"]
        listed = self.client.get(
            "/api/v1/server-backup-targets", headers=headers
        ).json()["items"]
        self.assertEqual(listed[0]["directory_path"], str(destination.resolve()))

        updated = self.client.put(
            f"/api/v1/server-backup-targets/{target_id}",
            headers=headers,
            json={
                "name": "測試 NAS",
                "directory_path": str(destination),
                "enabled": False,
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertFalse(
            self.client.get(
                "/api/v1/server-backup-targets", headers=headers
            ).json()["items"][0]["enabled"]
        )
        sync = self.client.post(
            "/api/v1/server-backup-targets/sync",
            headers=headers,
            json={"retention_days": 90, "max_count": 30},
        )
        self.assertEqual(sync.status_code, 409)
        deleted = self.client.delete(
            f"/api/v1/server-backup-targets/{target_id}", headers=headers
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_editor_can_write_contact_and_follow_up_but_viewer_cannot(self):
        admin_headers = self.login()
        created = self.client.post(
            f"/api/v1/records/{self.record_id}/contact-logs",
            headers=admin_headers,
            json={
                "contact_date": "2026-07-14",
                "method": "面談",
                "result": "願意再談",
                "next_follow_up": "2026-07-20",
                "note": "電話確認時間",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        log_id = created.json()["id"]
        logs = self.client.get(
            f"/api/v1/records/{self.record_id}/contact-logs", headers=admin_headers
        )
        self.assertEqual(logs.json()["items"][0]["result"], "願意再談")
        reminder = self.client.get(
            f"/api/v1/records/{self.record_id}/follow-up", headers=admin_headers
        )
        self.assertEqual(reminder.json()["item"]["due_date"], "2026-07-20")
        updated = self.client.put(
            f"/api/v1/records/{self.record_id}/follow-up",
            headers=admin_headers,
            json={"due_date": "2026-07-21", "status": "待回覆", "note": "再聯絡"},
        )
        self.assertEqual(updated.status_code, 204, updated.text)
        follow_ups = self.client.get("/api/v1/follow-ups", headers=admin_headers)
        self.assertEqual(follow_ups.json()["items"][0]["next_follow_up"], "2026-07-21")

        viewer_headers = self.login("viewer", "viewer-password")
        viewed = self.client.get(
            f"/api/v1/records/{self.record_id}", headers=viewer_headers
        )
        self.assertEqual(viewed.json()["external_id"], "H10******3")
        denied = self.client.post(
            f"/api/v1/records/{self.record_id}/contact-logs",
            headers=viewer_headers,
            json={"result": "不應寫入"},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(
            self.client.delete(
                f"/api/v1/records/{self.record_id}/contact-logs/{log_id}",
                headers=viewer_headers,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/v1/records/{self.record_id}/follow-up",
                headers=viewer_headers,
            ).status_code,
            403,
        )

        deleted_log = self.client.delete(
            f"/api/v1/records/{self.record_id}/contact-logs/{log_id}",
            headers=admin_headers,
        )
        self.assertEqual(deleted_log.status_code, 204, deleted_log.text)
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{self.record_id}/contact-logs",
                headers=admin_headers,
            ).json()["items"],
            [],
        )
        deleted_follow_up = self.client.delete(
            f"/api/v1/records/{self.record_id}/follow-up", headers=admin_headers
        )
        self.assertEqual(deleted_follow_up.status_code, 204, deleted_follow_up.text)
        self.assertIsNone(
            self.client.get(
                f"/api/v1/records/{self.record_id}/follow-up",
                headers=admin_headers,
            ).json()["item"]
        )

    def test_tag_crud_single_and_batch_assignment_enforces_roles(self):
        admin_headers = self.login()
        created = self.client.post(
            "/api/v1/tags",
            headers=admin_headers,
            json={"name": "優先拜訪", "color": "#ff8800"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        tag_id = created.json()["id"]
        self.assertEqual(
            self.client.get("/api/v1/tags", headers=admin_headers).json()["items"][0]["name"],
            "優先拜訪",
        )
        updated = self.client.put(
            f"/api/v1/tags/{tag_id}",
            headers=admin_headers,
            json={"name": "近期拜訪", "color": "#0088ff"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        assigned = self.client.put(
            f"/api/v1/records/{self.record_id}/tags",
            headers=admin_headers,
            json={"tag_ids": [tag_id, tag_id]},
        )
        self.assertEqual(assigned.json()["count"], 1)
        record_tags = self.client.get(
            f"/api/v1/records/{self.record_id}/tags", headers=admin_headers
        ).json()
        self.assertEqual(record_tags["tag_ids"], [tag_id])
        self.assertEqual(record_tags["items"][0]["name"], "近期拜訪")
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{self.record_id}", headers=admin_headers
            ).json()["tag_names"],
            "近期拜訪",
        )
        bulk = self.client.put(
            "/api/v1/tags/assignments",
            headers=admin_headers,
            json={
                "record_ids": [self.record_id],
                "tag_ids": [tag_id],
                "mode": "replace",
            },
        )
        self.assertEqual(bulk.json()["processed"], 1)

        viewer_headers = self.login("viewer", "viewer-password")
        self.assertEqual(
            self.client.get("/api/v1/tags", headers=viewer_headers).status_code, 200
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/tags",
                headers=viewer_headers,
                json={"name": "不可新增", "color": ""},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.put(
                "/api/v1/tags/assignments",
                headers=viewer_headers,
                json={"record_ids": [self.record_id], "tag_ids": [], "mode": "replace"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/tags",
                headers=admin_headers,
                json={"name": "錯誤顏色", "color": "orange"},
            ).status_code,
            422,
        )

        deleted = self.client.delete(
            f"/api/v1/tags/{tag_id}", headers=admin_headers
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{self.record_id}/tags", headers=admin_headers
            ).json()["tag_ids"],
            [],
        )

    def test_project_crud_assignments_and_roles(self):
        admin_headers = self.login()
        created = self.client.post(
            "/api/v1/projects",
            headers=admin_headers,
            json={"title": "中壢整合案", "status": "開發中", "note": "優先處理"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        project_id = created.json()["id"]

        projects = self.client.get(
            "/api/v1/projects", headers=admin_headers
        ).json()["items"]
        self.assertEqual(projects[0]["title"], "中壢整合案")
        self.assertEqual(projects[0]["customer_count"], 0)

        updated = self.client.put(
            f"/api/v1/projects/{project_id}",
            headers=admin_headers,
            json={"title": "中壢整合案（二期）", "status": "議價中", "note": "已更新"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)

        assigned = self.client.put(
            f"/api/v1/projects/{project_id}/records",
            headers=admin_headers,
            json={"record_ids": [self.record_id, self.record_id], "mode": "add"},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(assigned.json()["processed"], 1)
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{self.record_id}", headers=admin_headers
            ).json()["case_names"],
            "中壢整合案（二期）",
        )

        viewer_headers = self.login("viewer", "viewer-password")
        self.assertEqual(
            self.client.get("/api/v1/projects", headers=viewer_headers).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/projects",
                headers=viewer_headers,
                json={"title": "不可新增", "status": "進行中", "note": ""},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.put(
                f"/api/v1/projects/{project_id}/records",
                headers=viewer_headers,
                json={"record_ids": [self.record_id], "mode": "remove"},
            ).status_code,
            403,
        )

        removed = self.client.put(
            f"/api/v1/projects/{project_id}/records",
            headers=admin_headers,
            json={"record_ids": [self.record_id], "mode": "remove"},
        )
        self.assertEqual(removed.json()["processed"], 1)
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{self.record_id}", headers=admin_headers
            ).json()["case_names"],
            "",
        )
        self.assertEqual(
            self.client.delete(
                f"/api/v1/projects/{project_id}", headers=admin_headers
            ).status_code,
            204,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/v1/projects/{project_id}", headers=admin_headers
            ).status_code,
            404,
        )

    def test_desktop_productivity_endpoints_complete_remote_workflow(self):
        headers = self.login()

        field = self.client.post(
            "/api/v1/custom-fields",
            headers=headers,
            json={"label": "開發進度", "field_key": "development_stage"},
        )
        self.assertEqual(field.status_code, 201, field.text)
        field_id = field.json()["id"]
        values = self.client.put(
            f"/api/v1/records/{self.record_id}/custom-values",
            headers=headers,
            json={"values": {str(field_id): "已拜訪"}},
        )
        self.assertEqual(values.status_code, 200, values.text)
        stored_values = self.client.get(
            f"/api/v1/records/{self.record_id}/custom-values", headers=headers
        )
        self.assertEqual(stored_values.json()["values"][str(field_id)], "已拜訪")

        template = self.client.post(
            "/api/v1/text-templates",
            headers=headers,
            json={
                "title": "首次拜訪",
                "content": "已完成首次拜訪",
                "template_type": "visit_log",
            },
        )
        self.assertEqual(template.status_code, 201, template.text)
        templates = self.client.get("/api/v1/text-templates", headers=headers)
        self.assertEqual(templates.json()["items"][0]["title"], "首次拜訪")

        watchlist = self.client.put(
            "/api/v1/watchlist",
            headers=headers,
            json={"items": [{"name": "王大明", "note": "先電話聯絡"}]},
        )
        self.assertEqual(watchlist.json()["count"], 1)
        self.assertEqual(
            self.client.get("/api/v1/watchlist", headers=headers).json()["items"][0][
                "note"
            ],
            "先電話聯絡",
        )

        change_logs = self.client.post(
            "/api/v1/record-change-logs",
            headers=headers,
            json={
                "items": [
                    {
                        "record_id": self.record_id,
                        "action_type": "批次修改",
                        "field_key": "note",
                        "field_label": "備註",
                        "old_value": "",
                        "new_value": "完成",
                    }
                ]
            },
        )
        self.assertEqual(change_logs.json()["count"], 1)
        history = self.client.get(
            f"/api/v1/records/{self.record_id}/change-logs", headers=headers
        )
        self.assertEqual(history.json()["items"][0]["field_label"], "備註")

        operation = self.client.post(
            "/api/v1/operation-logs",
            headers=headers,
            json={"action_type": "測試", "summary": "遠端操作", "detail": "完成"},
        )
        self.assertEqual(operation.status_code, 201, operation.text)
        operation_logs = self.client.get("/api/v1/operation-logs", headers=headers)
        self.assertEqual(operation_logs.json()["items"][0]["summary"], "遠端操作")

        location = self.client.put(
            f"/api/v1/records/{self.record_id}/location",
            headers=headers,
            json={"latitude": 24.99, "longitude": 121.31, "source": "manual"},
        )
        self.assertEqual(location.status_code, 200, location.text)
        locations = self.client.get("/api/v1/record-locations", headers=headers)
        self.assertEqual(locations.json()["items"][0]["customer_id"], self.record_id)

        second_id = self.source.repository.save_customer(
            encrypt_record(
                self.fernet,
                self.record(
                    district="桃園區",
                    section="中正段",
                    land_number="100-2",
                    owner_name="王大明",
                ),
            )
        )
        ignored = self.client.post(
            "/api/v1/duplicate-reviews",
            headers=headers,
            json={
                "left_record_id": self.record_id,
                "right_record_id": second_id,
            },
        )
        self.assertEqual(ignored.status_code, 201, ignored.text)
        reviews = self.client.get("/api/v1/duplicate-reviews", headers=headers)
        self.assertEqual(len(reviews.json()["items"]), 1)

        attachment_check = self.client.post(
            "/api/v1/attachments/verify", headers=headers, json={}
        )
        self.assertEqual(attachment_check.status_code, 200, attachment_check.text)

        viewer_headers = self.login("viewer", "viewer-password")
        denied = self.client.put(
            "/api/v1/watchlist",
            headers=viewer_headers,
            json={"items": []},
        )
        self.assertEqual(denied.status_code, 403)

    def test_transactional_record_import_inserts_updates_and_enforces_roles(self):
        admin_headers = self.login()
        inserted_values = self.record(
            district="中壢區",
            section="青埔段",
            registration_order="20",
            land_number="200-8",
            area="660",
            declared_value="30000",
            numerator="1",
            denominator="2",
            owner_name="李小華",
            external_id="A123456789",
            address="匯入地址",
        )
        inserted_values.pop("name")
        updated_values = self.record(
            district="桃園區",
            section="中正段",
            registration_order="15",
            land_number="100-1",
            area="1000",
            declared_value="50000",
            numerator="1",
            denominator="2",
            owner_name="王大明",
            external_id="H100059743",
            address="Excel 更新地址",
        )
        updated_values.pop("name")
        imported = self.client.post(
            "/api/v1/imports/records",
            headers=admin_headers,
            json={
                "source_file_name": "地主清冊.xlsx",
                "items": [
                    {"record_id": None, "values": inserted_values},
                    {"record_id": self.record_id, "values": updated_values},
                ],
            },
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        result = imported.json()
        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["updated_ids"], [self.record_id])
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{self.record_id}", headers=admin_headers
            ).json()["address"],
            "Excel 更新地址",
        )
        self.assertEqual(
            self.client.get("/api/v1/records", headers=admin_headers).json()["total"],
            2,
        )

        viewer_headers = self.login("viewer", "viewer-password")
        denied = self.client.post(
            "/api/v1/imports/records",
            headers=viewer_headers,
            json={
                "source_file_name": "不可匯入.xlsx",
                "items": [{"record_id": None, "values": inserted_values}],
            },
        )
        self.assertEqual(denied.status_code, 403)

    def test_external_and_managed_attachments_enforce_roles_and_cleanup_files(self):
        admin_headers = self.login()
        external = self.client.post(
            f"/api/v1/records/{self.record_id}/attachments",
            headers=admin_headers,
            json={"file_path": "C:/documents/land.pdf", "description": "外部謄本"},
        )
        self.assertEqual(external.status_code, 201, external.text)
        external_id = external.json()["id"]

        content = b"managed attachment content"
        uploaded = self.client.post(
            f"/api/v1/records/{self.record_id}/attachments/upload",
            headers=admin_headers,
            files={"file": ("proof.txt", content, "text/plain")},
            data={"description": "納管附件"},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        managed_id = uploaded.json()["id"]

        attachments = self.client.get(
            f"/api/v1/records/{self.record_id}/attachments", headers=admin_headers
        ).json()["items"]
        by_id = {int(item["id"]): item for item in attachments}
        self.assertEqual(by_id[external_id]["status"], "external")
        self.assertEqual(by_id[managed_id]["status"], "managed")
        self.assertEqual(by_id[managed_id]["original_name"], "proof.txt")
        managed_path = Path(by_id[managed_id]["storage_path"])
        self.assertTrue(managed_path.is_file())
        self.assertTrue(managed_path.is_relative_to(self.settings.attachment_directory))
        downloaded = self.client.get(
            f"/api/v1/records/{self.record_id}/attachments/{managed_id}/content",
            headers=admin_headers,
        )
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, content)
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{self.record_id}/attachments/{external_id}/content",
                headers=admin_headers,
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{self.record_id}", headers=admin_headers
            ).json()["attachment_count"],
            2,
        )

        viewer_headers = self.login("viewer", "viewer-password")
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{self.record_id}/attachments",
                headers=viewer_headers,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/v1/records/{self.record_id}/attachments/{managed_id}",
                headers=viewer_headers,
            ).status_code,
            403,
        )

        self.assertEqual(
            self.client.delete(
                f"/api/v1/records/{self.record_id}/attachments/{managed_id}",
                headers=admin_headers,
            ).status_code,
            204,
        )
        self.assertFalse(managed_path.exists())
        self.assertEqual(
            self.client.delete(
                f"/api/v1/records/{self.record_id}/attachments/{external_id}",
                headers=admin_headers,
            ).status_code,
            204,
        )

    def test_record_crud_validates_calculates_encrypts_and_enforces_roles(self):
        admin_headers = self.login()
        payload = self.record(
            district="中壢區",
            section="青埔段",
            registration_order="20",
            land_number="200-5",
            area="660",
            declared_value="30000",
            numerator="1",
            denominator="2",
            owner_name="李小華",
            external_id="A123456789",
            address="桃園市中壢區測試路2號",
            note="API 新增",
        )
        payload.pop("name")
        created = self.client.post(
            "/api/v1/records", headers=admin_headers, json=payload
        )
        self.assertEqual(created.status_code, 201, created.text)
        created_id = created.json()["id"]

        detail = self.client.get(
            f"/api/v1/records/{created_id}", headers=admin_headers
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["owner_name"], "李小華")
        self.assertEqual(detail.json()["ping"], "99.83")
        self.assertEqual(detail.json()["total_declared_value"], "9,900,000")
        raw = self.source.repository.get_customer(created_id)
        self.assertTrue(str(raw["owner_name"]).startswith("enc:v1:"))

        payload["address"] = "桃園市中壢區更新路3號"
        updated = self.client.put(
            f"/api/v1/records/{created_id}",
            headers=admin_headers,
            json=payload,
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["id"], created_id)
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{created_id}", headers=admin_headers
            ).json()["address"],
            "桃園市中壢區更新路3號",
        )

        invalid = dict(payload, denominator="0")
        self.assertEqual(
            self.client.post(
                "/api/v1/records", headers=admin_headers, json=invalid
            ).status_code,
            422,
        )
        viewer_headers = self.login("viewer", "viewer-password")
        self.assertEqual(
            self.client.post(
                "/api/v1/records", headers=viewer_headers, json=payload
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/v1/records/{created_id}", headers=viewer_headers
            ).status_code,
            403,
        )

        deleted = self.client.delete(
            f"/api/v1/records/{created_id}", headers=admin_headers
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertEqual(
            self.client.get(
                f"/api/v1/records/{created_id}", headers=admin_headers
            ).status_code,
            404,
        )
        with self.source.database.connect() as conn:
            recycle_count = conn.execute(
                "SELECT COUNT(*) FROM recycle_bin WHERE original_id = ?",
                (created_id,),
            ).fetchone()[0]
        self.assertEqual(recycle_count, 1)

    def test_logout_revokes_session(self):
        headers = self.login()
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 200)
        self.assertEqual(
            self.client.post("/api/v1/auth/logout", headers=headers).status_code, 204
        )
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 401)

    def test_session_expiry_and_login_throttle(self):
        clock_value = [1000.0]
        sessions = SessionStore(ttl_seconds=60, clock=lambda: clock_value[0])
        user = self.source.authenticate("admin", "admin-password")
        token, _expires = sessions.create(user)
        self.assertIsNotNone(sessions.get(token))
        clock_value[0] += 61
        self.assertIsNone(sessions.get(token))

        throttle_clock = [50.0]
        throttle = LoginThrottle(
            max_failures=2, lock_seconds=30, clock=lambda: throttle_clock[0]
        )
        throttle.failure("client")
        self.assertEqual(throttle.retry_after("client"), 0)
        throttle.failure("client")
        self.assertEqual(throttle.retry_after("client"), 30)
        throttle_clock[0] += 31
        self.assertEqual(throttle.retry_after("client"), 0)

    def test_login_preserves_password_whitespace(self):
        self.source.repository.create_user(
            "space-user", " password with spaces ", "viewer", self.data_key
        )
        exact = self.client.post(
            "/api/v1/auth/login",
            json={"username": " space-user ", "password": " password with spaces "},
        )
        self.assertEqual(exact.status_code, 200, exact.text)
        trimmed = self.client.post(
            "/api/v1/auth/login",
            json={"username": "space-user", "password": "password with spaces"},
        )
        self.assertEqual(trimmed.status_code, 401)

    def test_migration_inventory_counts_shared_and_device_local_tables(self):
        counts = collect_source_counts(self.source.database)
        self.assertGreaterEqual(counts["users"], 1)
        self.assertEqual(counts["customers"], 1)
        self.assertEqual(set(EXTENDED_SOURCE_TABLES), set(counts) - {
            "users", "customers", "contact_logs", "follow_up_reminders",
            *DEVICE_LOCAL_TABLES,
        })
        for table in DEVICE_LOCAL_TABLES:
            self.assertIn(table, counts)


class PostgreSQLMigrationPlanTests(unittest.TestCase):
    def test_plan_normalizes_owner_land_and_preserves_every_ownership(self):
        records = [
            {
                "id": 1,
                "district": "桃園區",
                "section": "中正段",
                "land_number": "100",
                "owner_name": "王大明",
                "external_id": "H100059743",
                "address": "地址",
            },
            {
                "id": 2,
                "district": "桃園區",
                "section": "中正段",
                "land_number": "101",
                "owner_name": "王大明",
                "external_id": "h100059743",
                "address": "新地址",
            },
            {
                "id": 3,
                "district": "桃園區",
                "section": "中正段",
                "land_number": "100",
                "owner_name": "李小華",
                "external_id": "",
                "address": "另一地址",
            },
        ]
        plan = analyze_records(records, b"test-data-key")
        self.assertEqual(plan.source_records, 3)
        self.assertEqual(plan.owners, 2)
        self.assertEqual(plan.lands, 2)
        self.assertEqual(plan.ownerships, 3)
        self.assertEqual(plan.owners_with_identity, 1)
        self.assertEqual(plan.owners_without_identity, 1)
        self.assertEqual(
            owner_key_for(records[0], b"test-data-key"),
            owner_key_for(records[1], b"test-data-key"),
        )
        self.assertEqual(land_key_for(records[0]), land_key_for(records[2]))

    def test_complete_parallel_schema_and_json_normalization(self):
        schema_path = Path(__file__).resolve().parents[1] / "postgres" / "schema.sql"
        schema = schema_path.read_text(encoding="utf-8")
        self.assertIn("VALUES (2, 'desktop productivity mirror", schema)
        for table in (
            "project_ownerships",
            "project_tasks",
            "ownership_tags",
            "ownership_custom_values",
            "ownership_locations",
            "notifications",
            "operation_logs",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
        self.assertEqual(DEVICE_LOCAL_TABLES, ("app_settings", "backup_targets"))
        self.assertEqual(len(EXTENDED_SOURCE_TABLES), 19)
        self.assertEqual(_json_for_postgres('{"a": 1}', {}), '{"a": 1}')
        self.assertEqual(_json_for_postgres("legacy text", {}), '"legacy text"')


class LocalPostgreSQLConfigurationTests(unittest.TestCase):
    def test_dsn_is_protected_and_only_loaded_for_explicit_postgres_backend(self):
        with tempfile.TemporaryDirectory() as temporary:
            protected_path = Path(temporary) / "postgres-dsn.dpapi"
            dsn = "postgresql://local-user:secret@127.0.0.1:5432/land_customer"
            save_postgres_dsn(dsn, protected_path)
            self.assertEqual(load_postgres_dsn(protected_path), dsn)
            self.assertNotIn(b"secret", protected_path.read_bytes())

            with patch.dict(
                "os.environ",
                {"CUSTOMER_API_BACKEND": "sqlite"},
                clear=False,
            ):
                settings = ApiSettings.from_env()
            self.assertEqual(settings.backend, "sqlite")


class HomeServerLauncherTests(unittest.TestCase):
    def test_only_official_server_launcher_uses_crlf_and_keeps_failure_visible(self):
        root = Path(__file__).resolve().parents[1]
        launcher = root / "啟動家中伺服器.bat"
        content = launcher.read_bytes()
        self.assertTrue(content)
        self.assertEqual(content.count(b"\r\n"), content.count(b"\n"))
        text = content.decode("utf-8-sig")
        self.assertIn("home_server_runtime.ps1", text)
        self.assertIn("home-server-diagnostics.json", text)
        self.assertIn("pause >nul", text)

    def test_obsolete_server_launchers_are_removed(self):
        root = Path(__file__).resolve().parents[1]
        for name in (
            "start_api_server.bat",
            "start_api_server_postgresql.bat",
            "start_desktop_postgresql_preview.bat",
            "start_home_server_vpn.bat",
            "start_land_customer_system_postgresql.bat",
            "start_mobile_server_https.bat",
            "start_mobile_server_vpn.bat",
        ):
            self.assertFalse((root / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
