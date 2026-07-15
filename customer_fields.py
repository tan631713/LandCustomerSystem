"""Shared land-record field definitions used by desktop, API, and migrations."""


LAND_FIELDS = (
    ("district", "地區"),
    ("section", "地段"),
    ("registration_order", "序號"),
    ("land_number", "地號"),
    ("area", "面積/m2"),
    ("declared_value", "公告現值"),
    ("numerator", "分子"),
    ("denominator", "分母"),
    ("ping", "坪數"),
    ("total_declared_value", "總現值/元"),
    ("owner_name", "姓名"),
    ("external_id", "身分證"),
    ("address", "地址"),
    ("registration_reason", "原因"),
    ("note", "備註"),
    ("visit_log", "出訪記錄"),
)

LAND_FIELD_KEYS = tuple(key for key, _label in LAND_FIELDS)
