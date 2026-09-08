import unittest

from customer_domain import (
    build_duplicate_signature,
    calculate_ping,
    calculate_total_declared_value,
    mask_identity_text,
    normalize_taiwan_identity,
    normalize_search_text,
    parse_number,
    parse_rights_scope,
    parse_shared_land_rows,
    split_search_terms,
    split_rights_scope,
)


class CustomerDomainTests(unittest.TestCase):
    def test_number_and_rights_scope_parsing(self):
        self.assertEqual(parse_number("1,234"), 1234)
        self.assertEqual(parse_rights_scope("1/2"), 0.5)
        self.assertEqual(parse_rights_scope("2分之1"), 0.5)
        self.assertEqual(parse_rights_scope("25%"), 0.25)
        self.assertEqual(split_rights_scope("4分之3"), ("3", "4"))

    def test_land_value_and_ping_calculation(self):
        record = {
            "area": "100",
            "declared_value": "20,000",
            "numerator": "1",
            "denominator": "2",
        }

        self.assertEqual(calculate_total_declared_value(record), "1,000,000")
        self.assertEqual(calculate_ping(record), "15.12")

    def test_identity_mask_and_duplicate_signature(self):
        self.assertEqual(mask_identity_text("A123456789"), "A123*****9")
        self.assertEqual(mask_identity_text("A1234"), "A1234")
        self.assertEqual(
            normalize_taiwan_identity(" a123456789 "), "A123456789"
        )
        with self.assertRaisesRegex(ValueError, "格式不正確"):
            normalize_taiwan_identity("A123456788")
        first = {
            "district": " 中正區 ",
            "section": "一段",
            "subsection": "",
            "registration_order": "1",
            "land_number": "100",
            "owner_name": "王小明",
            "external_id": "A123",
        }
        second = {**first, "district": "中正區", "owner_name": "王小明"}

        self.assertEqual(build_duplicate_signature(first), build_duplicate_signature(second))

    def test_search_normalization_ignores_internal_and_full_width_whitespace(self):
        self.assertEqual(normalize_search_text(" 桃 園\u3000區 "), "桃園區")
        self.assertEqual(
            split_search_terms(" 中路、中路段，青溪段, 中 路 "),
            ("中路", "中路段", "青溪段"),
        )

    def test_shared_land_batch_rows_accept_excel_and_validate_rights(self):
        records, errors = parse_shared_land_rows(
            "姓名\t身分證\t地址\t分子\t分母\t備註\t出訪記錄\n"
            "王小明\tA123456789\t台北市\t1\t2\t重要\t已拜訪\n"
            '陳小華,B123456789,"新北市,板橋區",1,3'
        )
        self.assertFalse(errors)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["owner_name"], "王小明")
        self.assertEqual(records[1]["address"], "新北市,板橋區")

        records, errors = parse_shared_land_rows("錯誤資料\t\t\t1\t0")
        self.assertFalse(records)
        self.assertIn("分母必須大於 0", errors[0])

        records, errors = parse_shared_land_rows(
            "林先生、C123456789、桃園市、2、5、收購、追蹤、二訪"
        )
        self.assertFalse(errors)
        self.assertEqual(
            list(records[0]),
            [
                "owner_name",
                "external_id",
                "address",
                "numerator",
                "denominator",
                "registration_reason",
                "note",
                "visit_log",
            ],
        )
        self.assertEqual(records[0]["visit_log"], "二訪")

        records, errors = parse_shared_land_rows(
            "登記次序\t姓名\t身分證\t地址\t分子\t分母\t備註\t出訪記錄\n"
            "7\t林小姐\tD123456789\t台中市\t1\t4\t聯絡\t初訪"
        )
        self.assertFalse(errors)
        self.assertEqual(records[0]["registration_order"], "7")
        self.assertEqual(records[0]["owner_name"], "林小姐")

        records, errors = parse_shared_land_rows(
            "15、王弘益、H100059743、桃園市桃園區大華九街34號、108、3360"
        )
        self.assertFalse(errors)
        self.assertEqual(records[0]["registration_order"], "15")
        self.assertEqual(records[0]["owner_name"], "王弘益")
        self.assertEqual(records[0]["external_id"], "H100059743")
        self.assertEqual(records[0]["numerator"], "108")
        self.assertEqual(records[0]["denominator"], "3360")
        self.assertIsNone(records[0]["note"])
        self.assertIsNone(records[0]["visit_log"])


if __name__ == "__main__":
    unittest.main()
