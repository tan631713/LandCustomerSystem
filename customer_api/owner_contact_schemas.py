"""Validated API payloads for owner related people."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from customer_owner_contact_types import RELATIONSHIP_TYPES


class ContactWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    mobile_phone: str = Field(default="", max_length=30)
    home_phone: str = Field(default="", max_length=30)
    registered_address: str = Field(default="", max_length=500)
    contact_address: str = Field(default="", max_length=500)
    work_address: str = Field(default="", max_length=500)
    identity_note: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=2000)


class OwnerRelationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    relationship_type: str = Field(min_length=1, max_length=50)
    relationship_note: str = Field(default="", max_length=100)
    is_primary: bool = False
    sort_order: int = Field(default=0, ge=0, le=1_000_000)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_relationship(self):
        if self.relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError("關係類型不在允許清單中")
        if self.relationship_type == "其他" and not self.relationship_note:
            raise ValueError("選擇「其他」時必須填寫關係補充")
        return self


class OwnerContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact: ContactWrite
    relation: OwnerRelationWrite


class OwnerContactLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: int = Field(ge=1)
    relation: OwnerRelationWrite


class OwnerContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact: ContactWrite
    relation: OwnerRelationWrite
    expected_contact_updated_at: datetime | None = None
    expected_relation_updated_at: datetime | None = None


class OwnerContactDuplicateCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(default="", max_length=100)
    mobile_phone: str = Field(default="", max_length=30)
    home_phone: str = Field(default="", max_length=30)
    registered_address: str = Field(default="", max_length=500)
    contact_address: str = Field(default="", max_length=500)
    limit: int = Field(default=20, ge=1, le=50)


class OwnerContactDeactivate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(default="", max_length=500)
    expected_relation_updated_at: datetime | None = None


class OwnerContactReactivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_relation_updated_at: datetime | None = None
