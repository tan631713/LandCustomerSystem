import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

import customer_search as search_module
from customer_search import (
    CustomerDecryptionCache,
    CustomerRecordProcessor,
    CustomerSearchWorker,
)
from customer_security import encrypt_value, make_fernet


class CustomerSearchWorkerTests(unittest.TestCase):
    def test_processor_builds_filters_and_sorts_records(self):
        fernet = make_fernet(Fernet.generate_key())
        columns = [
            ("checked", ""),
            ("rowid", ""),
            ("district", ""),
            ("owner_name", ""),
            ("external_id", ""),
        ]
        row = {
            "id": 9,
            "district": "D",
            "section": "S",
            "registration_order": "1",
            "land_number": "100",
            "area": "10",
            "declared_value": "2000",
            "numerator": "1",
            "denominator": "2",
            "ping": "",
            "total_declared_value": "10000",
            "owner_name": encrypt_value(fernet, "Alice"),
            "external_id": encrypt_value(fernet, "A123456789"),
            "address": encrypt_value(fernet, "Address"),
            "registration_reason": "sale",
            "note": encrypt_value(fernet, "note"),
            "visit_log": encrypt_value(fernet, "visit"),
        }
        processor = CustomerRecordProcessor(
            fernet=fernet,
            table_columns=columns,
            checked_ids={9},
            watchlist_names={"alice"},
            checked_color="checked",
            watchlist_color="watchlist",
            note_color="note",
            keyword="alice",
        )

        record = processor.build_record(row)
        self.assertEqual(record["raw"]["owner_name"], "Alice")
        self.assertNotEqual(record["display"]["external_id"], "A123456789")
        self.assertEqual(record["background"], "checked")
        self.assertIn("owner_name", record["highlighted_fields"])
        self.assertEqual(processor.process([row]), [record])

    def test_processor_requires_all_advanced_search_conditions(self):
        fernet = make_fernet(Fernet.generate_key())
        base_row = {
            "id": 9,
            "district": "D",
            "section": "S",
            "registration_order": "1",
            "land_number": "100",
            "area": "10",
            "declared_value": "2000",
            "numerator": "1",
            "denominator": "2",
            "ping": "",
            "total_declared_value": "10000",
            "owner_name": encrypt_value(fernet, "Alice"),
            "external_id": encrypt_value(fernet, "A123456789"),
            "address": encrypt_value(fernet, "Address"),
            "registration_reason": "sale",
            "note": encrypt_value(fernet, ""),
            "visit_log": encrypt_value(fernet, ""),
        }
        partial_row = {**base_row, "id": 10, "section": "Other"}
        wrong_district_row = {**base_row, "id": 11, "district": "X"}
        processor = CustomerRecordProcessor(
            fernet=fernet,
            table_columns=[
                ("checked", ""),
                ("district", ""),
                ("section", ""),
                ("owner_name", ""),
            ],
            advanced_criteria={
                "district": "d",
                "section": "s、other",
                "owner_name": "ali",
            },
        )

        self.assertEqual(
            {
                record["id"]
                for record in processor.process(
                    [base_row, partial_row, wrong_district_row]
                )
            },
            {9, 10},
        )

    def test_worker_loads_and_processes_rows(self):
        results = []
        worker = CustomerSearchWorker(
            7,
            lambda: [1, 2, 3],
            lambda rows, is_cancelled: [value * 2 for value in rows]
            if not is_cancelled()
            else None,
        )
        worker.finished.connect(lambda request_id, rows: results.append((request_id, rows)))

        worker.run()

        self.assertEqual(results, [(7, [2, 4, 6])])

    def test_processor_searches_and_displays_management_metadata(self):
        fernet = make_fernet(Fernet.generate_key())
        row = {
            "id": 12,
            "district": "D",
            "section": "S",
            "registration_order": "1",
            "land_number": "100",
            "area": "10",
            "declared_value": "2000",
            "numerator": "1",
            "denominator": "2",
            "ping": "",
            "total_declared_value": "10000",
            "owner_name": encrypt_value(fernet, "Alice"),
            "external_id": encrypt_value(fernet, "A123456789"),
            "address": encrypt_value(fernet, "Address"),
            "registration_reason": "sale",
            "note": encrypt_value(fernet, ""),
            "visit_log": encrypt_value(fernet, ""),
            "case_names": "Priority Case",
            "tag_names": "Urgent、Visited",
            "primary_tag_color": "#ff0000",
            "tag_items": [
                {"tag_id": 1, "name": "Urgent", "color": "#ff0000"},
                {"tag_id": 2, "name": "Visited", "color": "#00ff00"},
            ],
            "attachment_count": 2,
            "custom_values": "Channel：phone",
            "last_contact": "2026-07-10 phone／answered",
            "next_follow_up": "2020-01-01",
            "follow_up_status": "待回覆",
        }
        columns = [
            ("checked", ""),
            ("rowid", ""),
            ("case_names", ""),
            ("tag_names", ""),
            ("attachment_count", ""),
            ("custom_values", ""),
            ("last_contact", ""),
            ("next_follow_up", ""),
            ("follow_up_status", ""),
        ]
        processor = CustomerRecordProcessor(
            fernet=fernet,
            table_columns=columns,
            keyword="urgent",
            filter_field="tag_names",
            overdue_color="overdue",
        )

        record = processor.build_record(row)

        self.assertEqual(record["raw"]["tag_names"], "Urgent、Visited")
        self.assertEqual(record["raw"]["attachment_count"], "2")
        self.assertEqual(record["tag_color"], "#FF0000")
        self.assertEqual(
            record["tags"],
            [
                {"tag_id": 1, "name": "Urgent", "color": "#FF0000"},
                {"tag_id": 2, "name": "Visited", "color": "#00FF00"},
            ],
        )
        self.assertTrue(record["is_overdue"])
        self.assertEqual(record["background"], "overdue")
        self.assertEqual(processor.process([row]), [record])

    def test_decryption_cache_reuses_values_and_invalidates_on_revision(self):
        fernet = make_fernet(Fernet.generate_key())
        row = {
            "id": 5,
            "district": "D",
            "section": "S",
            "registration_order": "1",
            "land_number": "100",
            "area": "10",
            "declared_value": "2000",
            "numerator": "1",
            "denominator": "2",
            "ping": "",
            "total_declared_value": "10000",
            "owner_name": encrypt_value(fernet, "Alice"),
            "external_id": encrypt_value(fernet, "A123456789"),
            "address": encrypt_value(fernet, "Address"),
            "registration_reason": "sale",
            "note": encrypt_value(fernet, "note"),
            "visit_log": encrypt_value(fernet, "visit"),
        }
        cache = CustomerDecryptionCache()
        cache.sync_revision(1)
        processor = CustomerRecordProcessor(
            fernet=fernet,
            table_columns=[("checked", ""), ("owner_name", "")],
            decryption_cache=cache,
        )

        with patch.object(
            search_module,
            "decrypt_value",
            wraps=search_module.decrypt_value,
        ) as decrypt:
            processor.build_record(row)
            processor.build_record(row)
            self.assertEqual(decrypt.call_count, 5)
            cache.sync_revision(2)
            processor.build_record(row)
            self.assertEqual(decrypt.call_count, 10)

    def test_worker_reports_loader_failure(self):
        failures = []

        def fail_to_load():
            raise RuntimeError("simulated search failure")

        worker = CustomerSearchWorker(11, fail_to_load, lambda rows, _cancelled: rows)
        worker.failed.connect(
            lambda request_id, message: failures.append((request_id, message))
        )

        worker.run()

        self.assertEqual(failures, [(11, "simulated search failure")])


if __name__ == "__main__":
    unittest.main()
