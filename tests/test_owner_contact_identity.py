import unittest
from types import SimpleNamespace

from cryptography.fernet import Fernet

from customer_api.postgres_owner_contacts import PostgreSQLOwnerContactMixin
from customer_security import ENCRYPTION_PREFIX, encrypt_value, make_fernet


class OwnerContactIdentityTests(unittest.TestCase):
    def setUp(self):
        self.key = Fernet.generate_key()
        self.user = SimpleNamespace(data_key=self.key)

    def test_contact_identity_uses_owner_encryption_and_default_masking(self):
        ciphertext = encrypt_value(make_fernet(self.key), "A123456789")
        self.assertTrue(ciphertext.startswith(ENCRYPTION_PREFIX))
        self.assertNotIn("A123456789", ciphertext)

        masked = PostgreSQLOwnerContactMixin._present_owner_contact(
            self.user, {"external_id": ciphertext}
        )
        self.assertEqual(masked["external_id"], "A123*****9")

        revealed = PostgreSQLOwnerContactMixin._present_owner_contact(
            self.user,
            {"external_id": ciphertext},
            reveal_identity=True,
        )
        self.assertEqual(revealed["external_id"], "A123456789")

    def test_empty_contact_identity_remains_empty(self):
        masked = PostgreSQLOwnerContactMixin._present_owner_contact(
            self.user, {"external_id": None}
        )
        self.assertEqual(masked["external_id"], "")


if __name__ == "__main__":
    unittest.main()
