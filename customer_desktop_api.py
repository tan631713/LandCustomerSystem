"""Desktop-side API client and record repository for PostgreSQL mode."""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import ssl
import time
import uuid
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
                urlopen_options = {"timeout": self.timeout_seconds}
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

    def save_project(self, title, status="進行中", note="", project_id=None):
        payload = {
            "title": str(title or "").strip(),
            "status": str(status or "進行中").strip() or "進行中",
            "note": str(note or "").strip(),
        }
        if project_id is None:
            result = self._request("POST", "/api/v1/projects", payload=payload)
        else:
            result = self._request(
                "PUT", f"/api/v1/projects/{int(project_id)}", payload=payload
            )
        return int(result["id"])

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

    def fetch_duplicate_candidates(self):
        return list(self._all_rows())

    def find_watchlist_match(self, _name):
        # 注意名單尚未搬到共用 API；預覽匯入不可回頭查本機 SQLite。
        return None

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

    def save_case(self, title, status="進行中", note="", case_id=None, **_unused):
        saved_id = self.client.save_project(title, status, note, case_id)
        self._invalidate()
        return int(saved_id)

    def delete_case(self, case_id):
        deleted = self.client.delete_project(int(case_id))
        self._invalidate()
        return int(bool(deleted))

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
