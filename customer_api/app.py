"""FastAPI application factory for local desktop/mobile synchronization."""

import hashlib
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from customer_api.auth import ApiSession, LoginThrottle, SessionStore
from customer_api.config import ApiSettings
from customer_api.data_sources import CustomerDataSource, create_data_source
from customer_api.types import AuthenticatedUser
from customer_domain import (
    calculate_ping,
    calculate_total_declared_value,
    format_number_text,
    format_ping_text,
    normalize_match_text,
    parse_number,
)
from customer_version import APP_VERSION


MOBILE_WEB_DIRECTORY = Path(__file__).resolve().parent.parent / "customer_mobile_web"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username", mode="before")
    @classmethod
    def trim_username(cls, value):
        return str(value).strip()


class ContactLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact_date: date | None = None
    method: str | None = Field(default=None, max_length=80)
    result: str | None = Field(default=None, max_length=200)
    next_follow_up: date | None = None
    note: str | None = Field(default=None, max_length=5000)


class FollowUpUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    due_date: date | None = None
    status: str = Field(default="未處理", min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=3000)


class ProjectWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    status: str = Field(default="進行中", min_length=1, max_length=100)
    note: str = Field(default="", max_length=5000)


class ProjectRecordsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_ids: list[int] = Field(min_length=1, max_length=5000)
    mode: Literal["add", "remove"] = "add"

    @field_validator("record_ids")
    @classmethod
    def normalize_record_ids(cls, values):
        return sorted({int(value) for value in values})


class TagWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="", max_length=20)

    @field_validator("color")
    @classmethod
    def validate_color(cls, value):
        text = str(value or "").strip()
        if text and (
            len(text) != 7
            or not text.startswith("#")
            or any(char not in "0123456789abcdefABCDEF" for char in text[1:])
        ):
            raise ValueError("color must use #RRGGBB format")
        return text


class RecordTagsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_ids: list[int] = Field(default_factory=list, max_length=1000)

    @field_validator("tag_ids")
    @classmethod
    def normalize_tag_ids(cls, values):
        return sorted({int(value) for value in values})


class BulkRecordTagsUpdate(RecordTagsUpdate):
    record_ids: list[int] = Field(min_length=1, max_length=5000)
    mode: Literal["add", "remove", "replace"] = "add"

    @field_validator("record_ids")
    @classmethod
    def normalize_record_ids(cls, values):
        return sorted({int(value) for value in values})


class ExternalAttachmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    file_path: str = Field(min_length=1, max_length=4096)
    description: str = Field(default="", max_length=1000)


class RecordWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    district: str = Field(min_length=1, max_length=100)
    section: str = Field(min_length=1, max_length=100)
    registration_order: str | None = Field(default=None, max_length=100)
    land_number: str = Field(min_length=1, max_length=100)
    area: str | None = Field(default=None, max_length=80)
    declared_value: str | None = Field(default=None, max_length=80)
    numerator: str | None = Field(default=None, max_length=80)
    denominator: str | None = Field(default=None, max_length=80)
    ping: str | None = Field(default=None, max_length=80)
    total_declared_value: str | None = Field(default=None, max_length=80)
    owner_name: str = Field(min_length=1, max_length=200)
    external_id: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=1000)
    registration_reason: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=5000)
    visit_log: str | None = Field(default=None, max_length=10000)

    @field_validator("*", mode="before")
    @classmethod
    def normalize_text_values(cls, value):
        if value is None:
            return None
        return str(value).strip()

    @model_validator(mode="after")
    def validate_numbers(self):
        for field_name in (
            "area",
            "declared_value",
            "numerator",
            "denominator",
            "ping",
            "total_declared_value",
        ):
            value = getattr(self, field_name)
            if value not in (None, "") and parse_number(value) is None:
                raise ValueError(f"{field_name} must be numeric")
        if self.denominator not in (None, "") and parse_number(self.denominator) == 0:
            raise ValueError("denominator must not be zero")
        return self

    def normalized_values(self):
        values = self.model_dump()
        values["declared_value"] = (
            format_number_text(values.get("declared_value")) or None
        )
        values["ping"] = (
            calculate_ping(values)
            or format_ping_text(values.get("ping"))
            or None
        )
        values["total_declared_value"] = (
            calculate_total_declared_value(values)
            or format_number_text(values.get("total_declared_value"))
            or None
        )
        return values


class ImportRecordItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: int | None = Field(default=None, ge=1)
    values: RecordWrite


class RecordImportBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_file_name: str = Field(default="import.xlsx", min_length=1, max_length=260)
    items: list[ImportRecordItem] = Field(min_length=1, max_length=5000)


def _number(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def _number_text(value):
    value = value.quantize(Decimal("0.01"))
    return format(value, "f")


def _stable_key(prefix, *parts):
    content = "\x1f".join(normalize_match_text(part) for part in parts)
    return hashlib.sha256(f"{prefix}:{content}".encode("utf-8")).hexdigest()[:24]


def _aggregate_owners(records):
    owners = {}
    for record in records:
        identity = str(record.get("external_id") or "").strip()
        name = str(record.get("owner_name") or record.get("name") or "").strip()
        address = str(record.get("address") or "").strip()
        owner_key = (
            _stable_key("identity", identity)
            if identity
            else _stable_key("owner", name, address)
        )
        owner = owners.setdefault(
            owner_key,
            {
                "owner_key": owner_key,
                "name": name,
                "external_id": identity,
                "address": address,
                "record_ids": [],
                "lands": set(),
                "total_ping": Decimal("0"),
                "total_declared_value": Decimal("0"),
            },
        )
        owner["record_ids"].append(int(record["id"]))
        owner["lands"].add(
            (
                str(record.get("district") or ""),
                str(record.get("section") or ""),
                str(record.get("land_number") or ""),
            )
        )
        owner["total_ping"] += _number(record.get("ping"))
        owner["total_declared_value"] += _number(record.get("total_declared_value"))
    result = []
    for owner in owners.values():
        result.append(
            {
                **{key: value for key, value in owner.items() if key not in {"lands", "total_ping", "total_declared_value"}},
                "record_count": len(owner["record_ids"]),
                "land_count": len(owner["lands"]),
                "total_ping": _number_text(owner["total_ping"]),
                "total_declared_value": _number_text(owner["total_declared_value"]),
            }
        )
    return sorted(result, key=lambda item: (item["name"], item["owner_key"]))


def _aggregate_lands(records):
    lands = {}
    for record in records:
        district = str(record.get("district") or "")
        section = str(record.get("section") or "")
        land_number = str(record.get("land_number") or "")
        land_key = _stable_key("land", district, section, land_number)
        land = lands.setdefault(
            land_key,
            {
                "land_key": land_key,
                "district": district,
                "section": section,
                "land_number": land_number,
                "area": record.get("area") or "",
                "declared_value": record.get("declared_value") or "",
                "owners": [],
            },
        )
        land["owners"].append(
            {
                "record_id": int(record["id"]),
                "name": record.get("owner_name") or record.get("name") or "",
                "external_id": record.get("external_id") or "",
                "numerator": record.get("numerator") or "",
                "denominator": record.get("denominator") or "",
                "ping": record.get("ping") or "",
                "total_declared_value": record.get("total_declared_value") or "",
            }
        )
    return sorted(
        lands.values(),
        key=lambda item: (item["district"], item["section"], item["land_number"]),
    )


def create_app(
    settings: ApiSettings | None = None,
    data_source: CustomerDataSource | None = None,
    session_store: SessionStore | None = None,
    login_throttle: LoginThrottle | None = None,
):
    settings = settings or ApiSettings.from_env()
    source = data_source or create_data_source(settings)
    sessions = session_store or SessionStore(settings.session_ttl_seconds)
    throttle = login_throttle or LoginThrottle()
    bearer = HTTPBearer(auto_error=False)

    app = FastAPI(
        title="土地資料系統 API",
        description="自架 Windows／iPhone 共用資料介面",
        version=APP_VERSION,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.data_source = source
    app.state.sessions = sessions

    @app.middleware("http")
    async def mobile_security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/mobile"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Permissions-Policy"] = (
                "camera=(), microphone=(), geolocation=(), payment=()"
            )
            if request.url.path.endswith("service-worker.js"):
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Service-Worker-Allowed"] = "/mobile/"
            elif request.url.path in {"/mobile", "/mobile/", "/mobile/index.html"}:
                response.headers["Cache-Control"] = "no-store"
        return response

    def current_session(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> ApiSession:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="請先登入。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        session = sessions.get(credentials.credentials)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登入已失效，請重新登入。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return session

    def editor_user(
        session: Annotated[ApiSession, Depends(current_session)],
    ) -> AuthenticatedUser:
        if session.user.role not in {"admin", "editor"}:
            raise HTTPException(status_code=403, detail="目前帳號只有檢視權限。")
        return session.user

    @app.get("/")
    def root():
        return {
            "name": "土地資料系統 API",
            "version": APP_VERSION,
            "docs": "/docs",
            "mobile": "/mobile/",
        }

    @app.get("/health")
    def health():
        try:
            return {**source.health(), "version": APP_VERSION}
        except Exception as exc:
            raise HTTPException(status_code=503, detail="資料庫目前無法使用。") from exc

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, request: Request):
        client_host = request.client.host if request.client else "unknown"
        throttle_key = f"{client_host}:{payload.username.casefold()}"
        retry_after = throttle.retry_after(throttle_key)
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="登入失敗次數過多，請稍後再試。",
                headers={"Retry-After": str(retry_after)},
            )
        user = source.authenticate(payload.username, payload.password)
        if user is None:
            throttle.failure(throttle_key)
            raise HTTPException(
                status_code=401,
                detail="帳號或密碼錯誤。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        throttle.success(throttle_key)
        token, expires_at = sessions.create(user)
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role,
            },
        }

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
        _session: Annotated[ApiSession, Depends(current_session)],
    ):
        if credentials:
            sessions.revoke(credentials.credentials)
        return None

    @app.get("/api/v1/auth/me")
    def me(session: Annotated[ApiSession, Depends(current_session)]):
        user = session.user
        return {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "expires_at": datetime.fromtimestamp(session.expires_at, timezone.utc).isoformat(),
        }

    @app.get("/api/v1/records")
    def records(
        session: Annotated[ApiSession, Depends(current_session)],
        q: str = Query(default="", max_length=200),
        district: str = Query(default="", max_length=100),
        section: str = Query(default="", max_length=100),
        land_number: str = Query(default="", max_length=100),
        owner_name: str = Query(default="", max_length=100),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1),
    ):
        return source.list_records(
            session.user,
            query=q,
            filters={
                "district": district,
                "section": section,
                "land_number": land_number,
                "owner_name": owner_name,
            },
            offset=offset,
            limit=min(limit, settings.max_page_size),
        )

    @app.get("/api/v1/records/{record_id}")
    def record_detail(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        record = source.get_record(session.user, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="找不到資料。")
        return record

    @app.post("/api/v1/records", status_code=201)
    def create_record(
        payload: RecordWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        record_id = source.save_record(user, payload.normalized_values())
        return {"id": record_id}

    @app.put("/api/v1/records/{record_id}")
    def replace_record(
        record_id: int,
        payload: RecordWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.save_record(
                user, payload.normalized_values(), record_id=record_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return {"id": saved_id}

    @app.delete("/api/v1/records/{record_id}", status_code=204)
    def delete_record(
        record_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            source.delete_record(user, record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return None

    @app.post("/api/v1/imports/records", status_code=201)
    def import_records(
        payload: RecordImportBatch,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        items = [
            {
                "record_id": item.record_id,
                "values": item.values.normalized_values(),
            }
            for item in payload.items
        ]
        try:
            return source.import_records(user, items, payload.source_file_name)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="匯入要更新的資料不存在。"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/records/{record_id}/contact-logs")
    def contact_logs(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        if source.get_record(session.user, record_id) is None:
            raise HTTPException(status_code=404, detail="找不到資料。")
        return {"items": source.list_contact_logs(session.user, record_id)}

    @app.post("/api/v1/records/{record_id}/contact-logs", status_code=201)
    def create_contact_log(
        record_id: int,
        payload: ContactLogCreate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        values = payload.model_dump(mode="json")
        try:
            log_id = source.add_contact_log(user, record_id, values)
            if values.get("next_follow_up"):
                source.save_follow_up(
                    user,
                    record_id,
                    {
                        "due_date": values["next_follow_up"],
                        "status": "未處理",
                        "note": values.get("note"),
                    },
                )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return {"id": log_id}

    @app.delete(
        "/api/v1/records/{record_id}/contact-logs/{log_id}", status_code=204
    )
    def delete_contact_log(
        record_id: int,
        log_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            deleted = source.delete_contact_log(user, record_id, log_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="找不到聯絡紀錄。")
        return None

    @app.get("/api/v1/records/{record_id}/follow-up")
    def get_follow_up(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        if source.get_record(session.user, record_id) is None:
            raise HTTPException(status_code=404, detail="找不到資料。")
        return {"item": source.get_follow_up(session.user, record_id)}

    @app.put("/api/v1/records/{record_id}/follow-up", status_code=204)
    def update_follow_up(
        record_id: int,
        payload: FollowUpUpdate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            source.save_follow_up(user, record_id, payload.model_dump(mode="json"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return None

    @app.delete("/api/v1/records/{record_id}/follow-up", status_code=204)
    def delete_follow_up(
        record_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            source.delete_follow_up(user, record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return None

    @app.get("/api/v1/follow-ups")
    def follow_ups(
        session: Annotated[ApiSession, Depends(current_session)],
        limit: int = Query(default=500, ge=1),
    ):
        return {
            "items": source.list_follow_ups(
                session.user, limit=min(limit, settings.max_page_size)
            )
        }

    @app.get("/api/v1/projects")
    def projects(session: Annotated[ApiSession, Depends(current_session)]):
        return {"items": source.list_projects(session.user)}

    @app.post("/api/v1/projects", status_code=201)
    def create_project(
        payload: ProjectWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            project_id = source.save_project(
                user, payload.title, payload.status, payload.note
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": project_id}

    @app.put("/api/v1/projects/{project_id}")
    def update_project(
        project_id: int,
        payload: ProjectWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.save_project(
                user,
                payload.title,
                payload.status,
                payload.note,
                project_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到案件。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": saved_id}

    @app.delete("/api/v1/projects/{project_id}", status_code=204)
    def delete_project(
        project_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        if not source.delete_project(user, project_id):
            raise HTTPException(status_code=404, detail="找不到案件。")
        return None

    @app.put("/api/v1/projects/{project_id}/records")
    def update_project_records(
        project_id: int,
        payload: ProjectRecordsUpdate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            if payload.mode == "add":
                processed = source.add_records_to_project(
                    user, project_id, payload.record_ids
                )
            else:
                processed = source.remove_records_from_project(
                    user, project_id, payload.record_ids
                )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="案件或資料不存在。"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"processed": processed}

    @app.get("/api/v1/tags")
    def tags(session: Annotated[ApiSession, Depends(current_session)]):
        return {"items": source.list_tags(session.user)}

    @app.post("/api/v1/tags", status_code=201)
    def create_tag(
        payload: TagWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            tag_id = source.save_tag(user, payload.name, payload.color)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": tag_id}

    @app.put("/api/v1/tags/assignments")
    def update_tag_assignments(
        payload: BulkRecordTagsUpdate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            processed = source.set_records_tags(
                user, payload.record_ids, payload.tag_ids, payload.mode
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="資料或標籤不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"processed": processed}

    @app.put("/api/v1/tags/{tag_id}")
    def update_tag(
        tag_id: int,
        payload: TagWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.save_tag(user, payload.name, payload.color, tag_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到標籤。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": saved_id}

    @app.delete("/api/v1/tags/{tag_id}", status_code=204)
    def delete_tag(
        tag_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        if not source.delete_tag(user, tag_id):
            raise HTTPException(status_code=404, detail="找不到標籤。")
        return None

    @app.get("/api/v1/records/{record_id}/tags")
    def record_tags(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        try:
            tag_ids = source.get_record_tag_ids(session.user, record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        items = [
            tag for tag in source.list_tags(session.user) if int(tag["id"]) in tag_ids
        ]
        return {"tag_ids": sorted(tag_ids), "items": items}

    @app.put("/api/v1/records/{record_id}/tags")
    def update_record_tags(
        record_id: int,
        payload: RecordTagsUpdate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            count = source.set_record_tags(user, record_id, payload.tag_ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="資料或標籤不存在。") from exc
        return {"count": count}

    @app.get("/api/v1/records/{record_id}/attachments")
    def record_attachments(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        try:
            items = source.list_attachments(session.user, record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return {"items": items}

    @app.post("/api/v1/records/{record_id}/attachments", status_code=201)
    def create_external_attachment(
        record_id: int,
        payload: ExternalAttachmentCreate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            attachment_id = source.add_external_attachment(
                user, record_id, payload.file_path, payload.description
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": attachment_id}

    @app.post(
        "/api/v1/records/{record_id}/attachments/upload", status_code=201
    )
    async def upload_managed_attachment(
        record_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
        file: UploadFile = File(...),
        description: str = Form(default="", max_length=1000),
    ):
        safe_name = Path(str(file.filename or "attachment")).name or "attachment"
        suffix = Path(safe_name).suffix[:20]
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                temporary_path = Path(handle.name)
                size = 0
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_attachment_size_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                "附件超過大小限制："
                                f"{settings.max_attachment_size_bytes // (1024 * 1024)} MB。"
                            ),
                        )
                    handle.write(chunk)
            try:
                attachment_id = source.import_managed_attachment(
                    user,
                    record_id,
                    temporary_path,
                    safe_name,
                    description,
                    file.content_type or "",
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="找不到資料。") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"id": attachment_id}
        finally:
            await file.close()
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @app.get(
        "/api/v1/records/{record_id}/attachments/{attachment_id}/content"
    )
    def attachment_content(
        record_id: int,
        attachment_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        try:
            attachment = source.get_attachment(
                session.user, record_id, attachment_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        if attachment is None:
            raise HTTPException(status_code=404, detail="找不到附件。")
        candidate = Path(str(attachment.get("storage_path") or "")).resolve()
        root = settings.attachment_directory.resolve()
        if (
            str(attachment.get("status") or "") == "external"
            or not candidate.is_relative_to(root)
        ):
            raise HTTPException(
                status_code=409, detail="外部連結附件只能在原電腦開啟。"
            )
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="附件檔案已遺失。")
        return FileResponse(
            candidate,
            media_type=attachment.get("media_type") or "application/octet-stream",
            filename=Path(str(attachment.get("original_name") or candidate.name)).name,
        )

    @app.delete(
        "/api/v1/records/{record_id}/attachments/{attachment_id}",
        status_code=204,
    )
    def delete_attachment(
        record_id: int,
        attachment_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            deleted = source.delete_attachment(user, record_id, attachment_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="找不到附件。")
        return None

    @app.get("/api/v1/owners")
    def owners(
        session: Annotated[ApiSession, Depends(current_session)],
        q: str = Query(default="", max_length=200),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1),
    ):
        records_result = source.list_records(
            session.user, query=q, offset=0, limit=100_000
        )
        items = _aggregate_owners(records_result["items"])
        limit = min(limit, settings.max_page_size)
        return {"total": len(items), "items": items[offset : offset + limit]}

    @app.get("/api/v1/lands")
    def lands(
        session: Annotated[ApiSession, Depends(current_session)],
        q: str = Query(default="", max_length=200),
        district: str = Query(default="", max_length=100),
        section: str = Query(default="", max_length=100),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1),
    ):
        records_result = source.list_records(
            session.user,
            query=q,
            filters={"district": district, "section": section},
            offset=0,
            limit=100_000,
        )
        items = _aggregate_lands(records_result["items"])
        limit = min(limit, settings.max_page_size)
        return {"total": len(items), "items": items[offset : offset + limit]}

    if MOBILE_WEB_DIRECTORY.is_dir():
        app.mount(
            "/mobile",
            StaticFiles(directory=MOBILE_WEB_DIRECTORY, html=True),
            name="mobile",
        )

    return app
