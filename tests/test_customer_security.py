import unittest

from customer_security import (
    DECRYPTION_ERROR_TEXT,
    derive_encryption_key,
    decrypt_value,
    encrypt_record,
    encrypt_value,
    hash_password,
    make_fernet,
    verify_password,
)


class CustomerSecurityTests(unittest.TestCase):
    def test_password_hash_verification(self):
        salt_hex, digest_hex = hash_password("correct horse battery staple")

        self.assertTrue(verify_password("correct horse battery staple", salt_hex, digest_hex))
        self.assertFalse(verify_password("wrong password", salt_hex, digest_hex))

    def test_encrypted_value_round_trip_and_idempotence(self):
        key = derive_encryption_key("password", "11" * 16)
        fernet = make_fernet(key)

        encrypted = encrypt_value(fernet, "王小明")

        self.assertNotEqual(encrypted, "王小明")
        self.assertEqual(encrypt_value(fernet, encrypted), encrypted)
        self.assertEqual(decrypt_value(fernet, encrypted), "王小明")

    def test_wrong_key_returns_safe_error_text(self):
        first = make_fernet(derive_encryption_key("first", "22" * 16))
        second = make_fernet(derive_encryption_key("second", "33" * 16))

        encrypted = encrypt_value(first, "private")

        self.assertEqual(decrypt_value(second, encrypted), DECRYPTION_ERROR_TEXT)

    def test_only_sensitive_record_fields_are_encrypted(self):
        fernet = make_fernet(derive_encryption_key("password", "44" * 16))
        record = {"district": "中正區", "owner_name": "王小明", "address": "台北市"}

        encrypted = encrypt_record(fernet, record)

        self.assertEqual(encrypted["district"], "中正區")
        self.assertNotEqual(encrypted["owner_name"], "王小明")
        self.assertNotEqual(encrypted["address"], "台北市")


if __name__ == "__main__":
    unittest.main()
