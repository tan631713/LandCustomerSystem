"""Validated request payloads for the customer API."""

from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from customer_domain import (
    calculate_ping,
    calculate_total_declared_value,
    format_number_text,
    format_ping_text,
    parse_number,
)


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
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    field_visit_route_item_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")
        return self


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
    assigned_to: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    priority: str = Field(default="一般", min_length=1, max_length=40)
    next_action: str | None = Field(default=None, max_length=1000)
    archived: bool = False


class ProjectTaskWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    assignee: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    status: str = Field(default="待處理", min_length=1, max_length=80)
    priority: str = Field(default="一般", min_length=1, max_length=40)
    checklist: str | None = Field(default=None, max_length=10000)


class NotificationMark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_ids: list[int] = Field(min_length=1, max_length=1000)
    action: Literal["read", "dismiss"] = "read"

    @field_validator("notification_ids")
    @classmethod
    def normalize_notification_ids(cls, values):
        return sorted({int(value) for value in values})


class IdList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(default_factory=list, max_length=5000)

    @field_validator("ids")
    @classmethod
    def normalize_ids(cls, values):
        return sorted({int(value) for value in values})


class RecordUndoCreate(IdList):
    operation_type: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)


class InsertUndoCreate(IdList):
    operation_type: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)


class CompositeUndoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_type: str = Field(min_length=1, max_length=100)
    snapshots: list[dict] = Field(default_factory=list, max_length=5000)
    inserted_ids: list[int] = Field(default_factory=list, max_length=5000)
    summary: str = Field(min_length=1, max_length=1000)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=256)
    role: Literal["admin", "editor", "viewer"] = "editor"
    display_name: str | None = Field(default=None, max_length=200)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(default=None, max_length=200)
    role: Literal["admin", "editor", "viewer"] | None = None
    active: bool | None = None


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=10, max_length=256)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class ServerBackupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(default="manual", min_length=1, max_length=40)
    retention_days: int = Field(default=90, ge=0, le=3650)
    max_count: int = Field(default=30, ge=3, le=9999)


class ServerBackupMaintenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_days: int = Field(default=90, ge=0, le=3650)
    max_count: int = Field(default=30, ge=3, le=9999)


class ServerBackupRestore(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    backup_name: str = Field(min_length=1, max_length=260)
    confirmation: str = Field(min_length=1, max_length=100)


class ServerBackupTargetWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    directory_path: str = Field(min_length=1, max_length=4096)
    enabled: bool = True


class ServerBackupTargetSync(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_days: int = Field(default=90, ge=0, le=3650)
    max_count: int = Field(default=30, ge=3, le=9999)


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
    category: str = Field(default="", max_length=50)
    field_visit_route_item_id: int | None = Field(default=None, ge=1)


class AttachmentMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    description: str = Field(default="", max_length=1000)
    category: str = Field(default="", max_length=50)


class RecordWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    district: str = Field(min_length=1, max_length=100)
    section: str = Field(min_length=1, max_length=100)
    subsection: str | None = Field(default=None, max_length=100)
    registration_order: str | None = Field(default=None, max_length=100)
    land_number: str = Field(min_length=1, max_length=100)
    area: str | None = Field(default=None, max_length=80)
    declared_value: str | None = Field(default=None, max_length=80)
    numerator: str | None = Field(default=None, max_length=80)
    denominator: str | None = Field(default=None, max_length=80)
    ping: str | None = Field(default=None, max_length=80)
    total_declared_value: str | None = Field(default=None, max_length=80)
    owner_name: str = Field(default="", max_length=200)
    external_id: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=1000)
    registration_reason: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=5000)
    visit_log: str | None = Field(default=None, max_length=10000)
    birth_year: str | None = Field(default=None, max_length=4)

    @field_validator("*", mode="before")
    @classmethod
    def normalize_text_values(cls, value, info: ValidationInfo):
        if value is None:
            if info.field_name == "owner_name":
                return ""
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
        if self.birth_year not in (None, ""):
            if not self.birth_year.isdigit() or len(self.birth_year) != 4:
                raise ValueError("birth_year must be a 4-digit Gregorian year")
            year = int(self.birth_year)
            if not (1900 <= year <= datetime.now().year):
                raise ValueError("birth_year is out of range")
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


class MergeRecordsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_id: int = Field(ge=1)
    secondary_id: int = Field(ge=1)
    values: RecordWrite

    @model_validator(mode="after")
    def validate_distinct_records(self):
        if self.primary_id == self.secondary_id:
            raise ValueError("merge requires two different records")
        return self


class ImportRecordItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: int | None = Field(default=None, ge=1)
    values: RecordWrite


class RecordImportBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_file_name: str = Field(default="import.xlsx", min_length=1, max_length=260)
    items: list[ImportRecordItem] = Field(min_length=1, max_length=5000)


class RecordChangeLogItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    record_id: int = Field(ge=1)
    action_type: str = Field(default="修改資料", min_length=1, max_length=100)
    field_key: str = Field(min_length=1, max_length=100)
    field_label: str = Field(min_length=1, max_length=100)
    old_value: str | None = Field(default=None, max_length=10000)
    new_value: str | None = Field(default=None, max_length=10000)


class RecordChangeLogBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RecordChangeLogItem] = Field(min_length=1, max_length=5000)


class RecordUpdateWithHistory(BaseModel):
    """Update one record and persist its field history in one transaction."""

    model_config = ConfigDict(extra="forbid")

    values: RecordWrite
    change_logs: list[RecordChangeLogItem] = Field(min_length=1, max_length=5000)


class CustomFieldWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=100)
    field_key: str | None = Field(default=None, max_length=64)


class CustomValuesWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[int, str | None] = Field(default_factory=dict, max_length=500)


class BulkCustomValuesWrite(CustomValuesWrite):
    record_ids: list[int] = Field(min_length=1, max_length=5000)

    @field_validator("record_ids")
    @classmethod
    def normalize_record_ids(cls, values):
        return sorted({int(value) for value in values})


class TextTemplateWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=10000)
    template_type: str = Field(default="note", min_length=1, max_length=80)


class WatchlistItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=3000)


class WatchlistReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WatchlistItem] = Field(default_factory=list, max_length=5000)


class OperationLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action_type: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)
    detail: str = Field(default="", max_length=10000)


class RecordLocationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    source: str = Field(default="manual", min_length=1, max_length=80)


class ExcelExportMark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_ids: list[int] = Field(min_length=1, max_length=5000)


class FieldVisitRouteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    visit_date: date
    title: str = Field(default="", max_length=200)
    start_latitude: float | None = Field(default=None, ge=-90, le=90)
    start_longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        if (self.start_latitude is None) != (self.start_longitude is None):
            raise ValueError("start_latitude and start_longitude must be supplied together")
        return self


class FieldVisitItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ownership_id: int = Field(ge=1)
    priority: int = 0
    route_order: int | None = Field(default=None, ge=1)
    is_order_locked: bool = False
    note: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def validate_locked_order(self):
        if self.is_order_locked and self.route_order is None:
            raise ValueError("a locked item requires route_order")
        return self


class FieldVisitItemsCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FieldVisitItemCreate] = Field(min_length=1, max_length=1000)

    @field_validator("items")
    @classmethod
    def reject_duplicate_ownerships(cls, items):
        ownership_ids = [item.ownership_id for item in items]
        if len(ownership_ids) != len(set(ownership_ids)):
            raise ValueError("items contain duplicate ownership_id values")
        return items


class FieldVisitItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: int | None = Field(default=None, ge=0, le=100)
    is_order_locked: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.priority is None and self.is_order_locked is None:
            raise ValueError("at least one field-visit item setting is required")
        return self


class FieldVisitStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    note: str = Field(default="", max_length=5000)
    postponed_until: datetime | None = None
    contact_date: date | None = None

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")
        return self


class FieldVisitOptimizePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_latitude: float = Field(ge=-90, le=90)
    current_longitude: float = Field(ge=-180, le=180)
    keep_current_item_first: bool = True
    current_item_id: int | None = Field(default=None, ge=1)


class FieldVisitOptimizeApply(FieldVisitOptimizePreview):
    plan_token: str = Field(min_length=64, max_length=64)


class FieldVisitManualOrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int = Field(ge=1)
    is_order_locked: bool = True


class FieldVisitManualOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FieldVisitManualOrderItem] = Field(min_length=1, max_length=1000)

    @field_validator("items")
    @classmethod
    def reject_duplicate_items(cls, items):
        item_ids = [item.item_id for item in items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("manual order contains duplicate item ids")
        return items


class DuplicateReviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_record_id: int = Field(ge=1)
    right_record_id: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_distinct_records(self):
        if self.left_record_id == self.right_record_id:
            raise ValueError("duplicate review requires two different records")
        return self
