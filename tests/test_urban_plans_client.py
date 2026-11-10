"""Urban plan (都市計畫) support in the desktop API client and record repository."""

import unittest

from cryptography.fernet import Fernet

from customer_desktop_api import DesktopApiClient, DesktopApiRecordRepository, LAND_LEVEL_FIELDS
from customer_fields import LAND_FIELDS
from customer_security import encrypt_record, make_fernet


class RecordingClient(DesktopApiClient):
    """The real client with the network replaced by a request log."""

    def __init__(self, responses=None):  # noqa: D107 - skip the real constructor
        self.sent = []
        self.responses = dict(responses or {})

    def _request(self, method, path, **kwargs):
        self.sent.append((method, path, kwargs.get("payload")))
        return self.responses.get((method, path), {})


class DesktopClientPlanRequestTests(unittest.TestCase):
    def test_import_sends_the_plan_only_when_one_was_chosen(self):
        client = RecordingClient()
        client.import_records([{"record_id": None, "values": {}}], "a.xlsx")
        client.import_records([{"record_id": None, "values": {}}], "a.xlsx", urban_plan_id=4)
        self.assertNotIn("urban_plan_id", client.sent[0][2])
        self.assertEqual(client.sent[1][2]["urban_plan_id"], 4)

    def test_plan_endpoints(self):
        client = RecordingClient({
            ("GET", "/api/v1/urban-plans"): {"items": [{"plan_id": 1, "name": "龍岡都市計畫"}]},
            ("POST", "/api/v1/urban-plans"): {"id": 7},
            ("PUT", "/api/v1/urban-plans/7"): {"id": 7},
            ("DELETE", "/api/v1/urban-plans/7"): {"deleted": True, "released_land_count": 3},
        })
        listed = client.list_urban_plans()
        self.assertEqual(listed["items"][0]["name"], "龍岡都市計畫")
        self.assertEqual(listed["unassigned"], {})
        self.assertEqual(client.save_urban_plan("  大湳都市計畫 "), 7)
        self.assertEqual(client.sent[-1], ("POST", "/api/v1/urban-plans", {"name": "大湳都市計畫"}))
        self.assertEqual(client.save_urban_plan("改名", 7), 7)
        self.assertEqual(client.sent[-1][:2], ("PUT", "/api/v1/urban-plans/7"))
        self.assertEqual(client.delete_urban_plan(7)["released_land_count"], 3)

    def test_assignment_payload(self):
        client = RecordingClient({("PUT", "/api/v1/urban-plans/assignments"): {"updated_count": 2}})
        client.set_lands_urban_plan([5, 3, 5], 9)
        self.assertEqual(
            client.sent[-1][2],
            {"land_ids": [3, 5], "urban_plan_id": 9, "only_unassigned": True},
        )
        client.set_lands_urban_plan([3], 0, only_unassigned=False)
        self.assertEqual(
            client.sent[-1][2],
            {"land_ids": [3], "urban_plan_id": None, "only_unassigned": False},
        )


class PlanServer:
    """Just enough of the home-server client to watch plan saves."""

    def __init__(self):
        self.list_all_calls = 0
        self.saved = []
        self.plan_calls = []
        self.import_calls = []
        self.next_id = 100
        self.rows = [
            self._row(4, land_id=10, land_number="100", plan=(1, "龍岡都市計畫")),
            self._row(3, land_id=10, land_number="100", plan=(1, "龍岡都市計畫")),
            self._row(2, land_id=20, land_number="200", plan=None),
            self._row(1, land_id=30, land_number="300", plan=None),
        ]

    @staticmethod
    def _row(record_id, *, land_id, land_number, plan):
        return {
            "id": record_id, "ownership_id": record_id, "land_id": land_id, "owner_id": record_id,
            "district": "中壢區", "section": "龍岡段", "subsection": "", "land_number": land_number,
            "area": "100", "declared_value": "5000", "owner_name": f"地主{record_id}",
            "name": f"地主{record_id}", "external_id": f"A{record_id}", "address": "某路 1 號",
            "note": "", "birth_year": "1960", "updated_at": "2026-01-01",
            "urban_plan_id": plan[0] if plan else None,
            "urban_plan_name": plan[1] if plan else None,
        }

    def list_all_records(self, **_kwargs):
        self.list_all_calls += 1
        return [dict(row) for row in self.rows]

    def get_record(self, record_id):
        return dict(next(row for row in self.rows if row["id"] == int(record_id)))

    def replace_record_with_history(self, record_id, values, _logs):
        self.saved.append(dict(values))
        return int(record_id)

    def replace_record(self, record_id, values):
        return self.replace_record_with_history(record_id, values, [])

    def create_record(self, values):
        self.saved.append(dict(values))
        self.next_id += 1
        row = self._row(self.next_id, land_id=99, land_number=values.get("land_number", ""), plan=None)
        row.update({key: value for key, value in values.items() if key != "urban_plan_id"})
        self.rows.insert(0, row)
        return self.next_id

    def list_urban_plans(self):
        self.plan_calls.append("list")
        return {
            "items": [
                {"plan_id": 1, "name": "龍岡都市計畫", "land_count": 1},
                {"plan_id": 2, "name": "大湳都市計畫", "land_count": 0},
            ],
            "unassigned": {"land_count": 2},
        }

    def save_urban_plan(self, name, plan_id=None):
        self.plan_calls.append(("save", name, plan_id))
        return plan_id or 3

    def delete_urban_plan(self, plan_id):
        self.plan_calls.append(("delete", plan_id))
        return {"deleted": True, "released_land_count": 1}

    def set_lands_urban_plan(self, land_ids, plan_id, only_unassigned=True):
        self.plan_calls.append(("assign", sorted(land_ids), plan_id, only_unassigned))
        return {"updated_count": len(land_ids), "updated_land_ids": list(land_ids), "kept_lands": []}

    def import_records(self, items, source_file_name, urban_plan_id=None):
        self.import_calls.append((len(items), urban_plan_id))
        return {"inserted_ids": [], "updated_ids": [], "inserted_count": 0, "updated_count": 0}


class RepositoryPlanTests(unittest.TestCase):
    def setUp(self):
        self.server = PlanServer()
        self.fernet = make_fernet(Fernet.generate_key())
        self.repository = DesktopApiRecordRepository(self.server, self.fernet)
        self.assertEqual(self.repository.count_customers(), 4)
        self.repository.list_urban_plans()

    def values(self, record_id, **changes):
        current = next(row for row in self.server.rows if row["id"] == record_id)
        values = {key: current.get(key, "") for key, _label in LAND_FIELDS}
        values.update(changes)
        return encrypt_record(self.fernet, values)

    def cached(self, record_id):
        return next(row for row in self.repository._all_rows() if row["id"] == record_id)

    def test_plan_fields_are_land_level_so_siblings_follow(self):
        self.assertIn("urban_plan_id", LAND_LEVEL_FIELDS)
        self.assertIn("urban_plan_name", LAND_LEVEL_FIELDS)

    def test_the_plan_listing_is_cached_until_something_changes(self):
        self.repository.list_urban_plans()
        self.assertEqual(self.server.plan_calls, ["list"])
        self.repository.list_urban_plans(refresh=True)
        self.assertEqual(self.server.plan_calls, ["list", "list"])

    def test_saving_without_a_plan_value_never_sends_one(self):
        self.repository.save_customer_with_change_logs(self.values(2, note="x"), 2, [])
        self.assertNotIn("urban_plan_id", self.server.saved[-1])

    def test_an_unchanged_plan_is_not_sent(self):
        self.repository.save_customer_with_change_logs(self.values(3, note="x", urban_plan_id=1), 3, [])
        self.repository.save_customer_with_change_logs(self.values(2, note="x", urban_plan_id=0), 2, [])
        self.assertTrue(all("urban_plan_id" not in saved for saved in self.server.saved))

    def test_changing_the_plan_is_sent_and_every_ownership_of_the_land_follows(self):
        self.repository.save_customer_with_change_logs(self.values(3, urban_plan_id=2), 3, [])
        self.assertEqual(self.server.saved[-1]["urban_plan_id"], 2)
        self.assertEqual((self.cached(3)["urban_plan_id"], self.cached(3)["urban_plan_name"]), (2, "大湳都市計畫"))
        self.assertEqual(self.cached(4)["urban_plan_name"], "大湳都市計畫")  # same land
        self.assertEqual(self.cached(2)["urban_plan_id"], None)  # another land
        self.assertEqual(self.server.list_all_calls, 1)

    def test_zero_releases_the_land_to_unclassified(self):
        self.repository.save_customer_with_change_logs(self.values(3, urban_plan_id=0), 3, [])
        self.assertEqual(self.server.saved[-1]["urban_plan_id"], 0)
        self.assertIsNone(self.cached(3)["urban_plan_id"])
        self.assertIsNone(self.cached(4)["urban_plan_name"])

    def test_a_plan_this_client_never_listed_falls_back_to_reloading(self):
        self.repository.save_customer_with_change_logs(self.values(2, urban_plan_id=77), 2, [])
        self.assertIsNone(self.repository._rows)

    def test_a_new_owner_joins_the_chosen_plan_on_an_unclassified_parcel(self):
        self.repository.save_customer(self.values(1, owner_name="新地主", urban_plan_id=2, external_id="Z9"))
        self.assertEqual(self.server.saved[-1]["urban_plan_id"], 2)

    def test_a_new_owner_never_moves_a_parcel_that_already_has_a_plan(self):
        self.repository.save_customer(self.values(3, owner_name="新地主", urban_plan_id=2, external_id="Z9"))
        self.assertNotIn("urban_plan_id", self.server.saved[-1])

    def test_a_new_unclassified_owner_sends_no_plan(self):
        self.repository.save_customer(self.values(1, owner_name="新地主", urban_plan_id=0, external_id="Z9"))
        self.assertNotIn("urban_plan_id", self.server.saved[-1])

    def test_plan_changes_reload_what_they_make_stale(self):
        self.repository.save_urban_plan("新計畫")
        self.assertIsNotNone(self.repository._rows)  # creating a plan changes no row
        self.repository.list_urban_plans()
        self.repository.save_urban_plan("龍岡 (改名)", 1)
        self.assertIsNone(self.repository._rows)  # rows still carry the old name
        self.repository.count_customers()
        self.assertEqual(self.repository.delete_urban_plan(1)["released_land_count"], 1)
        self.assertIsNone(self.repository._rows)
        self.repository.count_customers()
        result = self.repository.set_lands_urban_plan([20, 30], 2)
        self.assertEqual(result["updated_count"], 2)
        self.assertEqual(self.server.plan_calls[-1], ("assign", [20, 30], 2, True))
        self.assertIsNone(self.repository._rows)

    def test_import_passes_the_plan_only_when_one_is_given(self):
        record = {key: "" for key, _label in LAND_FIELDS}
        record.update(district="中壢區", land_number="1")
        self.repository.import_records([record])
        self.repository.import_records([record], urban_plan_id=2)
        self.assertEqual(self.server.import_calls, [(1, None), (1, 2)])


if __name__ == "__main__":
    unittest.main()
