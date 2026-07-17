"""Desktop-side API client and record repository for PostgreSQL mode."""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import ssl
import time
import uuid
from base64 import urlsafe_b64encode
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from customer_fields import LAND_FIELDS
from customer_security import ENCRYPTED_FIELDS, decrypt_value


DEFAULT_API_URL = "http://127.0.0.1:8732"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_CLIENT_ATTACHMENT_BYTES = 50 * 1024 * 1024
RECORD_FIELD_KEYS = frozenset(key for key, _label in LAND_FIELDS)


class DesktopApiError(RuntimeError):
    """Base error shown by desktop API mode."""


class DesktopApiConnectionError(DesktopApiError):
    """The API process or network cannot be reached."""


class DesktopApiResponseError(DesktopApiError):
    def __init__(self, status_code, detail):
        self.status_code = int(status_code)
        self.detail = str(detail or "API request failed")
        super().__init__(f"API {self.status_code}: {self.detail}")


class DesktopApiClient:
    def __init__(
        self,
        base_url=DEFAULT_API_URL,
        *,
        timeout_seconds=10,
        allow_insecure_lan=False,
        ca_certificate=None,
        urlopen_fn=None,
        read_retry_count=1,
        retry_delay_seconds=0.25,
        sleep_fn=None,
    ):
        self.base_url = str(base_url or DEFAULT_API_URL).strip().rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("API URL must use http or https")
        if (
            parsed.scheme != "https"
            and parsed.hostname.casefold() not in LOOPBACK_HOSTS
            and not allow_insecure_lan
        ):
            raise ValueError("Non-loopback desktop API connections must use HTTPS")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.read_retry_count = max(0, min(int(read_retry_count), 3))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self._sleep = sleep_fn or time.sleep
        self._urlopen = urlopen_fn or urlopen
        self._ssl_context = None
        if parsed.scheme == "https":
            configured_ca = str(
                ca_certificate
                or os.environ.get("LAND_CUSTOMER_API_CA_CERT", "")
            ).strip()
            if not configured_ca and os.name == "nt":
                local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
                if local_app_data:
                    candidate = (
                        Path(local_app_data)
                        / "LandCustomerSystem"
                        / "certificates"
                        / "land-customer-local-ca.pem"
                    )
                    if candidate.exists():
                        configured_ca = str(candidate)
            if configured_ca:
                ca_path = Path(configured_ca).expanduser().resolve()
                if not ca_path.is_file():
                    raise ValueError(f"API CA certificate does not exist: {ca_path}")
                self._ssl_context = ssl.create_default_context(cafile=str(ca_path))
        self.access_token = ""
        self.current_user = None

    @staticmethod
    def _connection_error_detail(exc):
        reason = getattr(exc, "reason", exc)
        reason_text = str(reason or exc)
        normalized = reason_text.casefold()
        if isinstance(reason, ssl.SSLCertVerificationError) or (
            "certificate_verify_failed" in normalized
            or "certificate verify failed" in normalized
        ):
            return (
                "HTTPS 憑證驗證失敗。請改用最新公司筆電客戶端包，"
                "或由家中主機重新建立客戶端包。"
            )
        if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in normalized:
            return "家中伺服器回應逾時。請確認家中主機未休眠且 NetBird 已連線。"
        if "connection refused" in normalized or "actively refused" in normalized:
            return "家中伺服器尚未啟動，或 8732 連接埠目前沒有服務。"
        if "network is unreachable" in normalized or "no route to host" in normalized:
            return "目前無法透過 NetBird 到達家中主機。"
        return f"無法連線至家中伺服器：{reason_text}"

    @property
    def authenticated(self):
        return bool(self.access_token)

    @staticmethod
    def _error_detail(payload, fallback):
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, list):
                extra_fields = []
                messages = []
                for item in detail:
                    if not isinstance(item, dict):
                        messages.append(str(item))
                        continue
                    location = list(item.get("loc") or [])
                    field_name = str(location[-1]) if location else "未知欄位"
                    if item.get("type") == "extra_forbidden":
                        extra_fields.append(field_name)
                        continue
                    message = str(item.get("msg") or "資料格式不正確")
                    messages.append(f"{field_name}：{message}")
                if extra_fields:
                    unique_fields = list(dict.fromkeys(extra_fields))
                    shown = "、".join(unique_fields[:10])
                    if len(unique_fields) > 10:
                        shown += f" 等 {len(unique_fields)} 個欄位"
                    messages.insert(0, f"包含系統不支援的欄位：{shown}")
                unique_messages = list(dict.fromkeys(messages))
                return "；".join(unique_messages[:10]) or str(fallback)
            if detail:
                return str(detail)
        return str(fallback)

    def _request(
        self,
        method,
        path,
        *,
        payload=None,
        params=None,
        authenticated=True,
        raw_body=None,
        content_type=None,
        timeout_seconds=None,
    ):
        query = urlencode(
            {
                key: value
                for key, value in dict(params or {}).items()
                if value not in (None, "")
            },
            doseq=True,
        )
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + query
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None and raw_body is not None:
            raise ValueError("payload and raw_body cannot be used together")
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        elif raw_body is not None:
            body = bytes(raw_body)
            headers["Content-Type"] = str(content_type or "application/octet-stream")
        if authenticated:
            if not self.access_token:
                raise DesktopApiResponseError(401, "尚未登入 API")
            headers["Authorization"] = f"Bearer {self.access_token}"
        request = Request(url, data=body, headers=headers, method=str(method).upper())
        request_method = str(method).upper()
        attempts = 1 + (self.read_retry_count if request_method == "GET" else 0)
        for attempt in range(attempts):
            try:
                urlopen_options = {
                    "timeout": self.timeout_seconds
                    if timeout_seconds is None
                    else max(1, int(timeout_seconds))
                }
                if self._ssl_context is not None:
                    urlopen_options["context"] = self._ssl_context
                with self._urlopen(request, **urlopen_options) as response:
                    raw = response.read()
                    if not raw:
                        return None
                    try:
                        return json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise DesktopApiError("家中 API 回傳了無法辨識的資料格式。") from exc
            except HTTPError as exc:
                try:
                    raw = exc.read()
                    error_payload = json.loads(raw.decode("utf-8")) if raw else {}
                except (UnicodeDecodeError, json.JSONDecodeError):
                    error_payload = {}
                finally:
                    exc.close()
                if exc.code == 401:
                    self.access_token = ""
                    self.current_user = None
                raise DesktopApiResponseError(
                    exc.code,
                    self._error_detail(error_payload, exc.reason),
                ) from exc
            except (URLError, TimeoutError, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                certificate_failure = isinstance(reason, ssl.SSLCertVerificationError) or (
                    "certificate_verify_failed" in str(reason).casefold()
                    or "certificate verify failed" in str(reason).casefold()
                )
                if attempt + 1 < attempts and not certificate_failure:
                    if self.retry_delay_seconds:
                        self._sleep(self.retry_delay_seconds)
                    continue
                raise DesktopApiConnectionError(
                    self._connection_error_detail(exc)
                ) from exc

    def health(self):
        return self._request("GET", "/health", authenticated=False)

    def login(self, username, password):
        result = self._request(
            "POST",
            "/api/v1/auth/login",
            payload={"username": str(username).strip(), "password": str(password)},
            authenticated=False,
        )
        self.access_token = str(result.get("access_token") or "")
        self.current_user = dict(result.get("user") or {})
        if not self.access_token:
            raise DesktopApiResponseError(500, "API 未回傳登入權杖")
        return dict(self.current_user)

    def logout(self):
        if self.access_token:
            try:
                self._request("POST", "/api/v1/auth/logout")
            finally:
                self.access_token = ""
                self.current_user = None

    def list_records(self, *, query="", filters=None, offset=0, limit=500):
        params = {"q": query, "offset": int(offset), "limit": int(limit)}
        params.update(dict(filters or {}))
        return self._request("GET", "/api/v1/records", params=params)

    def list_all_records(self, *, query="", filters=None, page_size=500):
        page_size = max(1, min(int(page_size), 500))
        items = []
        offset = 0
        while True:
            result = self.list_records(
                query=query,
                filters=filters,
                offset=offset,
                limit=page_size,
            )
            page = list(result.get("items") or [])
            items.extend(page)
            total = int(result.get("total") or 0)
            offset += len(page)
            if not page or offset >= total:
                return items

    def get_record(self, record_id):
        return self._request("GET", f"/api/v1/records/{int(record_id)}")

    def create_record(self, values):
        result = self._request("POST", "/api/v1/records", payload=dict(values))
        return int(result["id"])

    def replace_record(self, record_id, values):
        result = self._request(
            "PUT", f"/api/v1/records/{int(record_id)}", payload=dict(values)
        )
        return int(result["id"])

    def delete_record(self, record_id):
        self._request("DELETE", f"/api/v1/records/{int(record_id)}")
        return True

    def import_records(self, items, source_file_name="import.xlsx"):
        return self._request(
            "POST",
            "/api/v1/imports/records",
            payload={
                "source_file_name": str(source_file_name or "import.xlsx"),
                "items": list(items),
            },
        )

    def list_contact_logs(self, record_id):
        result = self._request(
            "GET", f"/api/v1/records/{int(record_id)}/contact-logs"
        )
        return list(result.get("items") or [])

    def add_contact_log(self, record_id, values):
        result = self._request(
            "POST",
            f"/api/v1/records/{int(record_id)}/contact-logs",
            payload=dict(values),
        )
        return int(result["id"])

    def delete_contact_log(self, record_id, log_id):
        self._request(
            "DELETE",
            f"/api/v1/records/{int(record_id)}/contact-logs/{int(log_id)}",
        )
        return True

    def get_follow_up(self, record_id):
        result = self._request(
            "GET", f"/api/v1/records/{int(record_id)}/follow-up"
        )
        return result.get("item")

    def save_follow_up(self, record_id, values):
        self._request(
            "PUT",
            f"/api/v1/records/{int(record_id)}/follow-up",
            payload=dict(values),
        )
        return True

    def delete_follow_up(self, record_id):
        self._request("DELETE", f"/api/v1/records/{int(record_id)}/follow-up")
        return True

    def list_follow_ups(self, limit=500):
        result = self._request(
            "GET", "/api/v1/follow-ups", params={"limit": int(limit)}
        )
        return list(result.get("items") or [])

    def list_projects(self):
        result = self._request("GET", "/api/v1/projects")
        return list(result.get("items") or [])

    def save_project(
        self, title, status="進行中", note="", project_id=None, **options
    ):
        payload = {
            "title": str(title or "").strip(),
            "status": str(status or "進行中").strip() or "進行中",
            "note": str(note or "").strip(),
            "assigned_to": str(options.get("assigned_to") or "").strip() or None,
            "due_date": str(options.get("due_date") or "").strip() or None,
            "priority": str(options.get("priority") or "一般").strip() or "一般",
            "next_action": str(options.get("next_action") or "").strip() or None,
            "archived": bool(options.get("archived", False)),
        }
        if project_id is None:
            result = self._request("POST", "/api/v1/projects", payload=payload)
        else:
            result = self._request(
                "PUT", f"/api/v1/projects/{int(project_id)}", payload=payload
            )
        return int(result["id"])

    def archive_project(self, project_id, archived=True):
        result = self._request(
            "PUT",
            f"/api/v1/projects/{int(project_id)}/archive",
            params={"archived": bool(archived)},
        )
        return int(result["id"])

    def list_project_tasks(self, project_id=None, include_completed=True):
        result = self._request(
            "GET", "/api/v1/project-tasks",
            params={
                "project_id": project_id,
                "include_completed": bool(include_completed),
            },
        )
        return list(result.get("items") or [])

    def save_project_task(self, project_id, title, task_id=None, **options):
        payload = {
            "project_id": int(project_id),
            "title": str(title or "").strip(),
            "assignee": str(options.get("assignee") or "").strip() or None,
            "due_date": str(options.get("due_date") or "").strip() or None,
            "status": str(options.get("status") or "待處理"),
            "priority": str(options.get("priority") or "一般"),
            "checklist": str(options.get("checklist") or "").strip() or None,
        }
        if task_id is None:
            result = self._request("POST", "/api/v1/project-tasks", payload=payload)
        else:
            result = self._request(
                "PUT", f"/api/v1/project-tasks/{int(task_id)}", payload=payload
            )
        return int(result["id"])

    def delete_project_task(self, task_id):
        self._request("DELETE", f"/api/v1/project-tasks/{int(task_id)}")
        return True

    def delete_project(self, project_id):
        self._request("DELETE", f"/api/v1/projects/{int(project_id)}")
        return True

    def update_project_records(self, project_id, record_ids, mode="add"):
        result = self._request(
            "PUT",
            f"/api/v1/projects/{int(project_id)}/records",
            payload={
                "record_ids": sorted({int(record_id) for record_id in record_ids}),
                "mode": str(mode or "add"),
            },
        )
        return int(result.get("processed") or 0)

    def list_tags(self):
        result = self._request("GET", "/api/v1/tags")
        return list(result.get("items") or [])

    def save_tag(self, name, color="", tag_id=None):
        payload = {"name": str(name or "").strip(), "color": str(color or "").strip()}
        if tag_id is None:
            result = self._request("POST", "/api/v1/tags", payload=payload)
        else:
            result = self._request(
                "PUT", f"/api/v1/tags/{int(tag_id)}", payload=payload
            )
        return int(result["id"])

    def delete_tag(self, tag_id):
        self._request("DELETE", f"/api/v1/tags/{int(tag_id)}")
        return True

    def get_record_tag_ids(self, record_id):
        result = self._request("GET", f"/api/v1/records/{int(record_id)}/tags")
        return {int(tag_id) for tag_id in result.get("tag_ids") or []}

    def set_record_tags(self, record_id, tag_ids):
        result = self._request(
            "PUT",
            f"/api/v1/records/{int(record_id)}/tags",
            payload={"tag_ids": sorted({int(tag_id) for tag_id in tag_ids})},
        )
        return int(result.get("count") or 0)

    def set_records_tags(self, record_ids, tag_ids, mode="add"):
        result = self._request(
            "PUT",
            "/api/v1/tags/assignments",
            payload={
                "record_ids": sorted({int(record_id) for record_id in record_ids}),
                "tag_ids": sorted({int(tag_id) for tag_id in tag_ids}),
                "mode": str(mode or "add"),
            },
        )
        return int(result.get("processed") or 0)

    def list_attachments(self, record_id):
        result = self._request(
            "GET", f"/api/v1/records/{int(record_id)}/attachments"
        )
        return list(result.get("items") or [])

    def add_external_attachment(self, record_id, file_path, description=""):
        result = self._request(
            "POST",
            f"/api/v1/records/{int(record_id)}/attachments",
            payload={
                "file_path": str(file_path or "").strip(),
                "description": str(description or "").strip(),
            },
        )
        return int(result["id"])

    def upload_managed_attachment(self, record_id, file_path, description=""):
        source = Path(file_path).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"找不到附件檔案：{source}")
        if source.stat().st_size > MAX_CLIENT_ATTACHMENT_BYTES:
            raise ValueError("附件超過大小限制：50 MB。")
        boundary = f"----LandCustomerBoundary{uuid.uuid4().hex}"
        safe_name = source.name.replace('"', "_")
        media_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        body = bytearray()

        def add_text(name, value):
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(
                    "ascii"
                )
            )
            body.extend(str(value or "").encode("utf-8"))
            body.extend(b"\r\n")

        add_text("description", description)
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            (
                'Content-Disposition: form-data; name="file"; '
                f'filename="{safe_name}"\r\n'
            ).encode("utf-8")
        )
        body.extend(f"Content-Type: {media_type}\r\n\r\n".encode("ascii"))
        body.extend(source.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("ascii"))
        result = self._request(
            "POST",
            f"/api/v1/records/{int(record_id)}/attachments/upload",
            raw_body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        return int(result["id"])

    def delete_attachment(self, record_id, attachment_id):
        self._request(
            "DELETE",
            f"/api/v1/records/{int(record_id)}/attachments/{int(attachment_id)}",
        )
        return True

    def list_record_change_logs(self, record_id, limit=300):
        result = self._request(
            "GET",
            f"/api/v1/records/{int(record_id)}/change-logs",
            params={"limit": int(limit)},
        )
        return list(result.get("items") or [])

    def add_record_change_logs(self, items):
        result = self._request(
            "POST",
            "/api/v1/record-change-logs",
            payload={"items": list(items)},
        )
        return int(result.get("count") or 0)

    def list_custom_fields(self):
        result = self._request("GET", "/api/v1/custom-fields")
        return list(result.get("items") or [])

    def save_custom_field(self, label, field_key=None, field_id=None):
        payload = {"label": str(label or "").strip(), "field_key": field_key or None}
        if field_id is None:
            result = self._request("POST", "/api/v1/custom-fields", payload=payload)
        else:
            result = self._request(
                "PUT", f"/api/v1/custom-fields/{int(field_id)}", payload=payload
            )
        return int(result["id"])

    def delete_custom_field(self, field_id):
        self._request("DELETE", f"/api/v1/custom-fields/{int(field_id)}")
        return True

    def get_record_custom_values(self, record_id):
        result = self._request(
            "GET", f"/api/v1/records/{int(record_id)}/custom-values"
        )
        return {
            int(field_id): value
            for field_id, value in dict(result.get("values") or {}).items()
        }

    def set_record_custom_values(self, record_id, values):
        result = self._request(
            "PUT",
            f"/api/v1/records/{int(record_id)}/custom-values",
            payload={"values": dict(values or {})},
        )
        return int(result.get("count") or 0)

    def set_records_custom_values(self, record_ids, values):
        result = self._request(
            "PUT",
            "/api/v1/custom-values/assignments",
            payload={
                "record_ids": sorted({int(value) for value in record_ids}),
                "values": dict(values or {}),
            },
        )
        return int(result.get("processed") or 0)

    def list_text_templates(self, template_type=None):
        params = {"template_type": template_type} if template_type else None
        result = self._request("GET", "/api/v1/text-templates", params=params)
        return list(result.get("items") or [])

    def save_text_template(
        self, title, content, template_type="note", template_id=None
    ):
        payload = {
            "title": str(title or "").strip(),
            "content": str(content or "").strip(),
            "template_type": str(template_type or "note").strip() or "note",
        }
        if template_id is None:
            result = self._request("POST", "/api/v1/text-templates", payload=payload)
        else:
            result = self._request(
                "PUT",
                f"/api/v1/text-templates/{int(template_id)}",
                payload=payload,
            )
        return int(result["id"])

    def delete_text_template(self, template_id):
        self._request("DELETE", f"/api/v1/text-templates/{int(template_id)}")
        return True

    def list_watchlist(self):
        result = self._request("GET", "/api/v1/watchlist")
        return list(result.get("items") or [])

    def replace_watchlist(self, items):
        result = self._request(
            "PUT", "/api/v1/watchlist", payload={"items": list(items)}
        )
        return int(result.get("count") or 0)

    def list_operation_logs(self, limit=300):
        result = self._request(
            "GET", "/api/v1/operation-logs", params={"limit": int(limit)}
        )
        return list(result.get("items") or [])

    def add_operation_log(self, action_type, summary, detail=""):
        result = self._request(
            "POST",
            "/api/v1/operation-logs",
            payload={
                "action_type": str(action_type or "").strip(),
                "summary": str(summary or "").strip(),
                "detail": str(detail or ""),
            },
        )
        return int(result["id"])

    def list_record_locations(self):
        result = self._request("GET", "/api/v1/record-locations")
        return list(result.get("items") or [])

    def set_record_location(
        self, record_id, latitude, longitude, source="manual"
    ):
        result = self._request(
            "PUT",
            f"/api/v1/records/{int(record_id)}/location",
            payload={
                "latitude": float(latitude),
                "longitude": float(longitude),
                "source": str(source or "manual"),
            },
        )
        return int(result["id"])

    def ignored_duplicate_pairs(self):
        result = self._request("GET", "/api/v1/duplicate-reviews")
        return {
            (int(item["left_record_id"]), int(item["right_record_id"]))
            for item in result.get("items") or []
        }

    def ignore_duplicate_pair(self, left_record_id, right_record_id):
        self._request(
            "POST",
            "/api/v1/duplicate-reviews",
            payload={
                "left_record_id": int(left_record_id),
                "right_record_id": int(right_record_id),
            },
        )
        return True

    def verify_managed_attachments(self):
        result = self._request("POST", "/api/v1/attachments/verify", payload={})
        return list(result.get("items") or [])

    def list_recycle_bin(self, limit=1000):
        result = self._request(
            "GET", "/api/v1/recycle-bin", params={"limit": int(limit)}
        )
        return list(result.get("items") or [])

    def restore_recycle_items(self, ids):
        result = self._request(
            "POST", "/api/v1/recycle-bin/restore", payload={"ids": list(ids)}
        )
        return [int(value) for value in result.get("record_ids") or []]

    def purge_recycle_items(self, ids=None):
        result = self._request(
            "POST", "/api/v1/recycle-bin/purge",
            params={"purge_all": ids is None},
            payload={"ids": [] if ids is None else list(ids)},
        )
        return int(result.get("count") or 0)

    def record_customer_undo(self, operation_type, ids, summary):
        result = self._request(
            "POST", "/api/v1/undo-operations/snapshot",
            payload={"operation_type": operation_type, "ids": list(ids), "summary": summary},
        )
        return result.get("id")

    def record_insert_undo(self, operation_type, ids, summary):
        result = self._request(
            "POST", "/api/v1/undo-operations/insert",
            payload={"operation_type": operation_type, "ids": list(ids), "summary": summary},
        )
        return result.get("id")

    def list_undo_operations(self, limit=100):
        result = self._request(
            "GET", "/api/v1/undo-operations", params={"limit": int(limit)}
        )
        return list(result.get("items") or [])

    def undo_operation(self, operation_id):
        return self._request(
            "POST", f"/api/v1/undo-operations/{int(operation_id)}/apply",
            payload={},
        )

    def merge_records(self, primary_id, secondary_id, values):
        result = self._request(
            "POST", "/api/v1/records/merge",
            payload={
                "primary_id": int(primary_id),
                "secondary_id": int(secondary_id),
                "values": dict(values),
            },
        )
        return int(result["id"])

    def refresh_notifications(self):
        result = self._request("POST", "/api/v1/notifications/refresh", payload={})
        return int(result.get("count") or 0)

    def list_notifications(self, include_read=False, limit=500):
        result = self._request(
            "GET", "/api/v1/notifications",
            params={"include_read": bool(include_read), "limit": int(limit)},
        )
        return list(result.get("items") or [])

    def mark_notifications(self, notification_ids, action="read"):
        result = self._request(
            "PUT", "/api/v1/notifications",
            payload={"notification_ids": list(notification_ids), "action": action},
        )
        return int(result.get("count") or 0)

    def list_users(self):
        result = self._request("GET", "/api/v1/users")
        return list(result.get("items") or [])

    def create_user(self, username, password, role, display_name=None):
        result = self._request(
            "POST", "/api/v1/users",
            payload={
                "username": username, "password": password, "role": role,
                "display_name": display_name,
            },
        )
        return int(result["id"])

    def update_user(self, user_id, **values):
        result = self._request(
            "PUT", f"/api/v1/users/{int(user_id)}", payload=dict(values)
        )
        return int(result["id"])

    def reset_user_password(self, user_id, new_password):
        result = self._request(
            "PUT", f"/api/v1/users/{int(user_id)}/password",
            payload={"new_password": new_password},
        )
        return int(result["id"])

    def change_password(self, current_password, new_password):
        result = self._request(
            "PUT", "/api/v1/auth/password",
            payload={"current_password": current_password, "new_password": new_password},
        )
        return bool(result.get("changed"))

    def encrypt_existing_records(self):
        return self._request(
            "POST",
            "/api/v1/maintenance/encrypt-existing-records",
            payload={},
            timeout_seconds=30 * 60,
        )

    def server_backup_status(self):
        return self._request("GET", "/api/v1/server-backups/status")

    def list_server_backups(self):
        result = self._request("GET", "/api/v1/server-backups")
        return list(result.get("items") or [])

    def create_server_backup(self, label="manual", retention_days=90, max_count=30):
        return self._request(
            "POST", "/api/v1/server-backups",
            payload={
                "label": label,
                "retention_days": int(retention_days),
                "max_count": int(max_count),
            },
            timeout_seconds=30 * 60,
        )

    def maintain_server_backups(self, retention_days=90, max_count=30):
        return self._request(
            "POST", "/api/v1/server-backups/maintenance",
            payload={
                "retention_days": int(retention_days),
                "max_count": int(max_count),
            },
            timeout_seconds=5 * 60,
        )

    def restore_server_backup(self, backup_name, confirmation):
        return self._request(
            "POST",
            "/api/v1/server-backups/restore",
            payload={"backup_name": backup_name, "confirmation": confirmation},
            timeout_seconds=30 * 60,
        )

    def list_server_backup_targets(self):
        result = self._request("GET", "/api/v1/server-backup-targets")
        return list(result.get("items") or [])

    def save_server_backup_target(
        self, name, directory_path, *, enabled=True, target_id=None
    ):
        method = "POST" if target_id is None else "PUT"
        path = (
            "/api/v1/server-backup-targets"
            if target_id is None
            else f"/api/v1/server-backup-targets/{int(target_id)}"
        )
        result = self._request(
            method,
            path,
            payload={
                "name": name,
                "directory_path": directory_path,
                "enabled": bool(enabled),
            },
        )
        return int(result["id"])

    def delete_server_backup_target(self, target_id):
        result = self._request(
            "DELETE", f"/api/v1/server-backup-targets/{int(target_id)}"
        )
        return bool(result.get("deleted"))

    def sync_server_backup_targets(self, retention_days=90, max_count=30):
        return self._request(
            "POST",
            "/api/v1/server-backup-targets/sync",
            payload={
                "retention_days": int(retention_days),
                "max_count": int(max_count),
            },
            timeout_seconds=30 * 60,
        )


class DesktopApiRecordRepository:
    """Core record subset consumed by the desktop search and edit workflow."""

    def __init__(self, client, fernet):
        self.client = client
        self.fernet = fernet
        self.data_revision = 0
        self._rows = None
        self.last_inserted_customer_ids = []
        self._contact_log_record_ids = {}
        self._attachment_record_ids = {}

    def _invalidate(self):
        self._rows = None
        self.data_revision += 1

    def _all_rows(self):
        if self._rows is None:
            self._rows = [dict(row) for row in self.client.list_all_records()]
        return self._rows

    def count_customers(self):
        return len(self._all_rows())

    def fetch_customer_page(self, limit, before_id=None):
        rows = sorted(self._all_rows(), key=lambda row: int(row["id"]), reverse=True)
        if before_id is not None:
            rows = [row for row in rows if int(row["id"]) < int(before_id)]
        return rows[: max(1, int(limit))]

    def fetch_search_candidate_rows(self, **_criteria):
        return list(self._all_rows())

    def fetch_all_customer_rows(self):
        return list(self._all_rows())

    def fetch_customer_ids(self):
        return {int(row["id"]) for row in self._all_rows()}

    def fetch_duplicate_candidates(self):
        return list(self._all_rows())

    def get_customer(self, record_id):
        record_id = int(record_id)
        for row in self._all_rows():
            if int(row["id"]) == record_id:
                return row
        return None

    def fetch_customers_by_ids(self, record_ids):
        wanted = {int(record_id) for record_id in record_ids}
        return [row for row in self._all_rows() if int(row["id"]) in wanted]

    def _plain_values(self, values):
        plain = {}
        for key, value in dict(values).items():
            if key not in RECORD_FIELD_KEYS:
                continue
            plain[key] = (
                decrypt_value(self.fernet, value)
                if key in ENCRYPTED_FIELDS
                else value
            )
        return plain

    def save_customer(self, values, record_id=None):
        plain = self._plain_values(values)
        saved_id = (
            self.client.create_record(plain)
            if record_id is None
            else self.client.replace_record(int(record_id), plain)
        )
        self._invalidate()
        return int(saved_id)

    def update_customers(self, records):
        records = list(records)
        for record in records:
            self.client.replace_record(
                int(record["id"]), self._plain_values(record)
            )
        if records:
            self._invalidate()
        return len(records)

    def delete_customers(self, record_ids):
        deleted = 0
        for record_id in sorted({int(value) for value in record_ids}):
            self.client.delete_record(record_id)
            deleted += 1
        if deleted:
            self._invalidate()
        return deleted

    def delete_all_customers(self):
        return self.delete_customers(self.fetch_customer_ids())

    def get_record_change_logs(self, record_id, limit=300):
        return [
            dict(row)
            for row in self.client.list_record_change_logs(record_id, limit=limit)
        ]

    def add_record_change_logs(self, logs):
        items = []
        for log in logs:
            items.append(
                {
                    "record_id": int(log.get("record_id") or log.get("customer_id")),
                    "action_type": str(log.get("action_type") or "修改資料"),
                    "field_key": str(log.get("field_key") or ""),
                    "field_label": str(
                        log.get("field_label") or log.get("field_key") or ""
                    ),
                    "old_value": log.get("old_value"),
                    "new_value": log.get("new_value"),
                }
            )
        return self.client.add_record_change_logs(items) if items else 0

    def import_records(
        self,
        inserted_records,
        updated_records=(),
        source_file_name="import.xlsx",
    ):
        items = [
            {"record_id": None, "values": self._plain_values(record)}
            for record in inserted_records
        ]
        items.extend(
            {
                "record_id": int(record["id"]),
                "values": self._plain_values(record),
            }
            for record in updated_records
        )
        if not items:
            self.last_inserted_customer_ids = []
            return {
                "batch_id": None,
                "inserted_count": 0,
                "updated_count": 0,
                "inserted_ids": [],
                "updated_ids": [],
            }
        result = dict(self.client.import_records(items, source_file_name))
        self.last_inserted_customer_ids = [
            int(record_id) for record_id in result.get("inserted_ids") or []
        ]
        self._invalidate()
        return result

    def insert_customers(self, records):
        result = self.import_records(records, source_file_name="desktop-batch.xlsx")
        return int(result.get("inserted_count") or 0)

    def list_contact_logs(self, record_id):
        record_id = int(record_id)
        rows = [dict(row) for row in self.client.list_contact_logs(record_id)]
        for row in rows:
            self._contact_log_record_ids[int(row["id"])] = record_id
        return rows

    def add_contact_log(
        self,
        record_id,
        contact_date=None,
        method=None,
        result=None,
        next_follow_up=None,
        note=None,
    ):
        record_id = int(record_id)
        log_id = self.client.add_contact_log(
            record_id,
            {
                "contact_date": contact_date or None,
                "method": method or None,
                "result": result or None,
                "next_follow_up": next_follow_up or None,
                "note": decrypt_value(self.fernet, note) or None,
            },
        )
        self._contact_log_record_ids[int(log_id)] = record_id
        self._invalidate()
        return int(log_id)

    def delete_contact_log(self, log_id):
        log_id = int(log_id)
        record_id = self._contact_log_record_ids.get(log_id)
        if record_id is None:
            raise DesktopApiError(
                "找不到聯絡紀錄所屬資料，請重新開啟聯絡紀錄後再試。"
            )
        deleted = self.client.delete_contact_log(record_id, log_id)
        self._contact_log_record_ids.pop(log_id, None)
        self._invalidate()
        return int(bool(deleted))

    def get_follow_up_reminder(self, record_id):
        reminder = self.client.get_follow_up(int(record_id))
        return dict(reminder) if reminder is not None else None

    def save_follow_up_reminder(
        self, record_id, due_date=None, status="未處理", note=None
    ):
        self.client.save_follow_up(
            int(record_id),
            {
                "due_date": due_date or None,
                "status": status or "未處理",
                "note": decrypt_value(self.fernet, note) or None,
            },
        )
        self._invalidate()

    def delete_follow_up_reminder(self, record_id):
        deleted = self.client.delete_follow_up(int(record_id))
        self._invalidate()
        return int(bool(deleted))

    def list_follow_up_reminders(self, limit=500):
        rows = []
        for item in self.client.list_follow_ups(limit=limit):
            row = dict(item)
            row["customer_id"] = int(row.get("id") or row.get("customer_id"))
            row["due_date"] = row.get("next_follow_up") or ""
            row["status"] = row.get("follow_up_status") or ""
            rows.append(row)
        return rows

    def list_cases(self):
        return [dict(row) for row in self.client.list_projects()]

    def save_case(self, title, status="進行中", note="", case_id=None, **options):
        saved_id = self.client.save_project(title, status, note, case_id, **options)
        self._invalidate()
        return int(saved_id)

    def delete_case(self, case_id):
        deleted = self.client.delete_project(int(case_id))
        self._invalidate()
        return int(bool(deleted))

    def archive_case(self, case_id, archived=True):
        return self.client.archive_project(case_id, archived)

    def list_case_tasks(self, case_id=None, include_completed=True):
        return [
            dict(row) for row in self.client.list_project_tasks(
                case_id, include_completed
            )
        ]

    def save_case_task(self, case_id, title, task_id=None, **options):
        return self.client.save_project_task(
            case_id, title, task_id=task_id, **options
        )

    def delete_case_task(self, task_id):
        return int(bool(self.client.delete_project_task(task_id)))

    def add_customers_to_case(self, case_id, customer_ids):
        processed = self.client.update_project_records(
            int(case_id), customer_ids, "add"
        )
        self._invalidate()
        return int(processed)

    def remove_customers_from_case(self, case_id, customer_ids):
        processed = self.client.update_project_records(
            int(case_id), customer_ids, "remove"
        )
        self._invalidate()
        return int(processed)

    def list_tags(self):
        return [dict(row) for row in self.client.list_tags()]

    def save_tag(self, name, color="", tag_id=None):
        saved_id = self.client.save_tag(name, color, tag_id)
        self._invalidate()
        return int(saved_id)

    def delete_tag(self, tag_id):
        deleted = self.client.delete_tag(int(tag_id))
        self._invalidate()
        return int(bool(deleted))

    def get_customer_tag_ids(self, customer_id):
        return set(self.client.get_record_tag_ids(int(customer_id)))

    def set_customer_tags(self, customer_id, tag_ids):
        count = self.client.set_record_tags(int(customer_id), tag_ids)
        self._invalidate()
        return int(count)

    def set_customers_tags(self, customer_ids, tag_ids, mode="add"):
        processed = self.client.set_records_tags(customer_ids, tag_ids, mode)
        self._invalidate()
        return int(processed)

    def list_customer_attachments(self, customer_id):
        customer_id = int(customer_id)
        rows = [
            dict(row) for row in self.client.list_attachments(customer_id)
        ]
        for row in rows:
            self._attachment_record_ids[int(row["id"])] = customer_id
        return rows

    def add_customer_attachment(self, customer_id, file_path, description=""):
        customer_id = int(customer_id)
        attachment_id = self.client.add_external_attachment(
            customer_id, file_path, description
        )
        self._attachment_record_ids[int(attachment_id)] = customer_id
        self._invalidate()
        return int(attachment_id)

    def import_managed_attachment(
        self, customer_id, source_path, _storage_root, description=""
    ):
        customer_id = int(customer_id)
        attachment_id = self.client.upload_managed_attachment(
            customer_id, source_path, description
        )
        self._attachment_record_ids[int(attachment_id)] = customer_id
        self._invalidate()
        return int(attachment_id)

    def delete_customer_attachment(self, attachment_id, _storage_root=None):
        attachment_id = int(attachment_id)
        customer_id = self._attachment_record_ids.get(attachment_id)
        if customer_id is None:
            raise DesktopApiError(
                "找不到附件所屬資料，請重新開啟附件管理後再試。"
            )
        deleted = self.client.delete_attachment(customer_id, attachment_id)
        self._attachment_record_ids.pop(attachment_id, None)
        self._invalidate()
        return int(bool(deleted))

    def list_custom_fields(self):
        return [dict(row) for row in self.client.list_custom_fields()]

    def save_custom_field(self, label, field_key=None, field_id=None):
        saved_id = self.client.save_custom_field(label, field_key, field_id)
        self._invalidate()
        return int(saved_id)

    def delete_custom_field(self, field_id):
        deleted = self.client.delete_custom_field(field_id)
        self._invalidate()
        return int(bool(deleted))

    def get_customer_custom_values(self, customer_id):
        return self.client.get_record_custom_values(customer_id)

    def set_customer_custom_values(self, customer_id, values_by_field_id):
        count = self.client.set_record_custom_values(customer_id, values_by_field_id)
        self._invalidate()
        return int(count)

    def set_customers_custom_values(self, customer_ids, values_by_field_id):
        count = self.client.set_records_custom_values(customer_ids, values_by_field_id)
        self._invalidate()
        return int(count)

    def list_text_templates(self, template_type=None):
        return [
            dict(row)
            for row in self.client.list_text_templates(template_type=template_type)
        ]

    def save_text_template(
        self, title, content, template_type="note", template_id=None
    ):
        return int(
            self.client.save_text_template(
                title, content, template_type, template_id
            )
        )

    def delete_text_template(self, template_id):
        return int(bool(self.client.delete_text_template(template_id)))

    def get_watchlist_entries(self):
        return [dict(row) for row in self.client.list_watchlist()]

    def replace_watchlist_entries(self, entries):
        return int(self.client.replace_watchlist(entries))

    def find_watchlist_match(self, name):
        target = "".join(str(name or "").split()).casefold()
        if not target:
            return None
        for row in self.get_watchlist_entries():
            normalized = "".join(str(row.get("name") or "").split()).casefold()
            if normalized == target:
                return row
        return None

    def get_operation_logs(self, limit=300):
        return [dict(row) for row in self.client.list_operation_logs(limit)]

    def log_operation(self, action_type, summary, detail=None):
        return int(
            self.client.add_operation_log(action_type, summary, detail or "")
        )

    def list_customer_locations(self):
        return [dict(row) for row in self.client.list_record_locations()]

    def set_customer_location(self, customer_id, latitude, longitude, source="manual"):
        return int(
            self.client.set_record_location(
                customer_id, latitude, longitude, source
            )
        )

    def ignored_duplicate_pairs(self):
        return set(self.client.ignored_duplicate_pairs())

    def ignore_duplicate_pair(self, left_id, right_id):
        return int(bool(self.client.ignore_duplicate_pair(left_id, right_id)))

    def verify_managed_attachments(self):
        return [dict(row) for row in self.client.verify_managed_attachments()]

    def list_recycle_bin(self, limit=1000):
        return [dict(row) for row in self.client.list_recycle_bin(limit)]

    def restore_recycle_items(self, ids):
        restored = self.client.restore_recycle_items(ids)
        self._invalidate()
        return restored

    def purge_recycle_items(self, ids=None, _storage_root=None):
        return self.client.purge_recycle_items(ids)

    def record_customer_undo(self, operation_type, ids, summary):
        return self.client.record_customer_undo(operation_type, ids, summary)

    def record_insert_undo(self, operation_type, ids, summary):
        return self.client.record_insert_undo(operation_type, ids, summary)

    def list_undo_operations(self, limit=100):
        return [dict(row) for row in self.client.list_undo_operations(limit)]

    def undo_operation(self, operation_id=None):
        if operation_id is None:
            rows = [row for row in self.list_undo_operations() if row.get("status") == "available"]
            if not rows:
                return None
            operation_id = rows[0]["id"]
        result = self.client.undo_operation(operation_id)
        self._invalidate()
        return result

    def merge_customers(self, primary_id, secondary_id, merged_record):
        result = self.client.merge_records(
            primary_id, secondary_id, self._plain_values(merged_record)
        )
        self._invalidate()
        return result

    def refresh_notifications(self, _today_text=None):
        return self.client.refresh_notifications()

    def list_notifications(self, include_read=False, limit=500):
        return [dict(row) for row in self.client.list_notifications(include_read, limit)]

    def mark_notifications(self, notification_ids, action="read"):
        return self.client.mark_notifications(notification_ids, action)

    def list_users(self):
        return [dict(row) for row in self.client.list_users()]

    def create_user(self, username, password, role, _data_key=None, display_name=None):
        return self.client.create_user(username, password, role, display_name)

    def update_user(self, user_id, **values):
        return self.client.update_user(user_id, **values)

    def reset_user_password(self, user_id, new_password, _data_key=None):
        return self.client.reset_user_password(user_id, new_password)

    def change_user_password(self, _username, current_password, new_password, _data_key=None):
        self.client.change_password(current_password, new_password)
        data_key = urlsafe_b64encode(
            self.fernet._signing_key + self.fernet._encryption_key
        )
        return data_key, None

    def change_admin_password(self, current_password, new_password):
        return self.change_user_password("admin", current_password, new_password)

    def encrypt_existing_customers(self, _fernet=None):
        result = dict(self.client.encrypt_existing_records())
        self._invalidate()
        return int(result.get("updated_records") or 0)

    def server_backup_status(self):
        return dict(self.client.server_backup_status())

    def list_server_backups(self):
        return [dict(row) for row in self.client.list_server_backups()]

    def create_server_backup(self, label="manual", retention_days=90, max_count=30):
        return dict(
            self.client.create_server_backup(label, retention_days, max_count)
        )

    def maintain_server_backups(self, retention_days=90, max_count=30):
        return dict(
            self.client.maintain_server_backups(retention_days, max_count)
        )

    def restore_server_backup(self, backup_name, confirmation):
        return dict(self.client.restore_server_backup(backup_name, confirmation))

    def list_server_backup_targets(self):
        return [dict(row) for row in self.client.list_server_backup_targets()]

    def save_server_backup_target(
        self, name, directory_path, *, enabled=True, target_id=None
    ):
        return self.client.save_server_backup_target(
            name,
            directory_path,
            enabled=enabled,
            target_id=target_id,
        )

    def delete_server_backup_target(self, target_id):
        return self.client.delete_server_backup_target(target_id)

    def sync_server_backup_targets(self, retention_days=90, max_count=30):
        return dict(
            self.client.sync_server_backup_targets(retention_days, max_count)
        )
