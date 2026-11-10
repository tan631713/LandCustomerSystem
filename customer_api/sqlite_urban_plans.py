"""The standalone SQLite data source has no urban plans (home server feature)."""

_UNSUPPORTED = "單機版資料來源不支援都市計畫，請連線至家中伺服器。"


class SQLiteUrbanPlanMixin:
    def list_urban_plans(self, user):
        del user
        return {
            "items": [],
            "unassigned": {"land_count": 0, "ownership_count": 0, "owner_count": 0},
        }

    def save_urban_plan(self, user, name, plan_id=None):
        raise ValueError(_UNSUPPORTED)

    def delete_urban_plan(self, user, plan_id):
        raise ValueError(_UNSUPPORTED)

    def set_lands_urban_plan(self, user, land_ids, plan_id, only_unassigned=True):
        raise ValueError(_UNSUPPORTED)
