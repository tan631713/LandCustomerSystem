import unittest

from customer_api.schemas import RecordWrite
from customer_postgres_keys import owner_key_for


class BlankOwnerImportTests(unittest.TestCase):
    def test_api_record_accepts_omitted_or_null_owner_name(self):
        required_land = {
            "district": "中壢區",
            "section": "中路段",
            "subsection": "",
            "land_number": "1-3",
        }

        omitted = RecordWrite.model_validate(required_land)
        explicit_null = RecordWrite.model_validate(
            {**required_land, "owner_name": None}
        )

        self.assertEqual(omitted.owner_name, "")
        self.assertEqual(explicit_null.owner_name, "")
        self.assertEqual(explicit_null.normalized_values()["owner_name"], "")

    def test_blank_owners_on_different_lands_do_not_share_owner_key(self):
        first = {
            "district": "中壢區",
            "section": "中路段",
            "subsection": "",
            "land_number": "1-3",
            "owner_name": "",
        }
        second = {
            "district": "中壢區",
            "section": "中路段",
            "subsection": "",
            "land_number": "1-5",
            "owner_name": None,
        }

        self.assertNotEqual(
            owner_key_for(first, b"data-key"),
            owner_key_for(second, b"data-key"),
        )

    def test_blank_owner_key_is_stable_for_same_land(self):
        record = {
            "district": "中壢區",
            "section": "中路段",
            "subsection": "",
            "land_number": "1-3",
            "owner_name": None,
        }

        self.assertEqual(
            owner_key_for(record, b"data-key"),
            owner_key_for(dict(record), b"data-key"),
        )


if __name__ == "__main__":
    unittest.main()
