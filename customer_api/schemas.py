"""Validated request payloads for the customer API."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from customer_domain import (
    calculate_ping,
    calculate_total_declared_value,
    format_number_text,
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


class DuplicateReviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_record_id: int = Field(ge=1)
    right_record_id: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_distinct_records(self):
        if self.left_record_id == self.right_record_id:
            raise ValueError("duplicate review requires two different records")
        return self
