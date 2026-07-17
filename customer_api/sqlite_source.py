"""SQLite implementation of the customer API data-source contract."""

from customer_api.config import ApiSettings
from customer_api.sqlite_attachments import SQLiteAttachmentMixin
from customer_api.sqlite_collaboration import SQLiteCollaborationMixin
from customer_api.sqlite_desktop_features import SQLiteDesktopFeatureMixin
from customer_api.sqlite_projects import SQLiteProjectMixin
from customer_api.sqlite_records import SQLiteRecordMixin
from customer_api.sqlite_tags import SQLiteTagMixin
from customer_api.types import AuthenticatedUser
from customer_database import CustomerDatabase
from customer_fields import LAND_FIELDS
from customer_repository import CustomerRepository


class SQLiteCustomerDataSource(
    SQLiteRecordMixin,
    SQLiteCollaborationMixin,
    SQLiteProjectMixin,
    SQLiteTagMixin,
    SQLiteAttachmentMixin,
    SQLiteDesktopFeatureMixin,
):
    backend_name = "sqlite"

    def __init__(self, settings: ApiSettings):
        self.settings = settings
        self.database = CustomerDatabase(
            settings.sqlite_database_path,
            settings.backup_directory,
        )
        self.repository = CustomerRepository(
            self.database,
            settings.schema_path,
            settings.seed_path,
            LAND_FIELDS,
        )
        self.repository.init_db()

    def health(self):
        with self.database.connect() as conn:
            schema_version = self.repository.migrations.current_version(conn)
            record_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        return {
            "status": "ok",
            "backend": self.backend_name,
            "schema_version": int(schema_version),
            "record_count": int(record_count),
        }

    def authenticate(self, username, password):
        data_key = self.repository.authenticate_user(str(username), str(password))
        user = self.repository.last_authenticated_user
        if not data_key or not user:
            return None
        return AuthenticatedUser(
            id=int(user["id"]),
            username=str(user["username"]),
            display_name=str(user["display_name"]),
            role=str(user["role"]),
            data_key=bytes(data_key),
        )
