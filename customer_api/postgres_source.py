"""PostgreSQL implementation of the customer API data-source contract."""

from customer_api.config import ApiSettings
from customer_api.postgres_attachments import PostgreSQLAttachmentMixin
from customer_api.postgres_collaboration import PostgreSQLCollaborationMixin
from customer_api.postgres_desktop_features import PostgreSQLDesktopFeatureMixin
from customer_api.postgres_projects import PostgreSQLProjectMixin
from customer_api.postgres_records import PostgreSQLRecordMixin
from customer_api.postgres_tags import PostgreSQLTagMixin
from customer_api.types import AuthenticatedUser
from customer_security import derive_encryption_key, make_fernet, verify_password


class PostgreSQLCustomerDataSource(
    PostgreSQLRecordMixin,
    PostgreSQLCollaborationMixin,
    PostgreSQLProjectMixin,
    PostgreSQLTagMixin,
    PostgreSQLAttachmentMixin,
    PostgreSQLDesktopFeatureMixin,
):
    backend_name = "postgresql"
    CONNECT_TIMEOUT_SECONDS = 5

    RECORD_SELECT = """
        SELECT ownership.id,
               land.district, land.section, ownership.registration_order,
               land.land_number, land.area, land.declared_value,
               ownership.numerator, ownership.denominator, ownership.ping,
               ownership.total_declared_value,
               owner.owner_name, owner.external_id, owner.address,
               ownership.registration_reason, ownership.note,
               ownership.visit_log, owner.owner_name AS name,
               ownership.created_at, ownership.updated_at,
               COALESCE((
                   SELECT STRING_AGG(project.title, '、' ORDER BY project.updated_at DESC, project.id DESC)
                   FROM project_ownerships membership
                   JOIN projects project ON project.id = membership.project_id
                   WHERE membership.ownership_id = ownership.id
               ), '') AS case_names,
               COALESCE((
                   SELECT STRING_AGG(tag.name, '、' ORDER BY tag.name, tag.id)
                   FROM ownership_tags link
                   JOIN tags tag ON tag.id = link.tag_id
                   WHERE link.ownership_id = ownership.id
               ), '') AS tag_names,
               COALESCE((
                   SELECT tag.color
                   FROM ownership_tags link
                   JOIN tags tag ON tag.id = link.tag_id
                   WHERE link.ownership_id = ownership.id
                     AND COALESCE(tag.color, '') <> ''
                   ORDER BY tag.name, tag.id
                   LIMIT 1
               ), '') AS primary_tag_color,
               (
                   SELECT COUNT(*)::integer
                   FROM attachments attachment
                   WHERE attachment.ownership_id = ownership.id
               ) AS attachment_count,
               COALESCE((
                   SELECT STRING_AGG(
                       CASE
                           WHEN COALESCE(attachment.description, '') <> ''
                           THEN attachment.description || '（' || COALESCE(attachment.file_path, attachment.original_name) || '）'
                           ELSE COALESCE(attachment.file_path, attachment.original_name)
                       END,
                       '；' ORDER BY attachment.created_at DESC, attachment.id DESC
                   )
                   FROM attachments attachment
                   WHERE attachment.ownership_id = ownership.id
               ), '') AS attachment_names,
               COALESCE((
                   SELECT STRING_AGG(
                       field.label || '：' || COALESCE(custom_value.value, ''),
                       '；' ORDER BY field.id
                   )
                   FROM ownership_custom_values custom_value
                   JOIN custom_fields field ON field.id = custom_value.field_id
                   WHERE custom_value.ownership_id = ownership.id
               ), '') AS custom_values,
               COALESCE((
                   SELECT CONCAT_WS('／', NULLIF(log.method, ''), NULLIF(log.result, ''))
                   FROM contact_logs log
                   WHERE log.ownership_id = ownership.id
                   ORDER BY COALESCE(log.contact_date, log.created_at::date) DESC, log.id DESC
                   LIMIT 1
               ), '') AS last_contact,
               COALESCE(reminder.due_date::text, '') AS next_follow_up,
               COALESCE(reminder.status, '') AS follow_up_status
        FROM ownerships ownership
        JOIN owners owner ON owner.id = ownership.owner_id
        JOIN lands land ON land.id = ownership.land_id
        LEFT JOIN follow_up_reminders reminder ON reminder.ownership_id = ownership.id
    """

    def __init__(self, settings: ApiSettings):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "尚未安裝 PostgreSQL 驅動，請安裝 requirements-server.txt"
            ) from exc
        self.settings = settings
        self.dsn = settings.postgres_dsn
        self._psycopg = psycopg
        self._dict_row = dict_row

    def _connect(self):
        return self._psycopg.connect(
            self.dsn,
            row_factory=self._dict_row,
            connect_timeout=self.CONNECT_TIMEOUT_SECONDS,
        )

    def health(self):
        with self._connect() as conn:
            schema_row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            count_row = conn.execute("SELECT COUNT(*) AS count FROM ownerships").fetchone()
        return {
            "status": "ok",
            "backend": self.backend_name,
            "schema_version": int(schema_row["version"]),
            "record_count": int(count_row["count"]),
        }

    def authenticate(self, username, password):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, role, active,
                       password_salt, password_hash, encryption_salt, wrapped_data_key
                FROM users WHERE username = %s
                """,
                (str(username),),
            ).fetchone()
            if (
                row is None
                or not row["active"]
                or not verify_password(password, row["password_salt"], row["password_hash"])
            ):
                return None
            wrapping_key = derive_encryption_key(password, row["encryption_salt"])
            if row["wrapped_data_key"]:
                try:
                    data_key = make_fernet(wrapping_key).decrypt(
                        row["wrapped_data_key"].encode("ascii")
                    )
                except Exception:
                    return None
            else:
                data_key = wrapping_key
            conn.execute(
                "UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = %s",
                (row["id"],),
            )
        return AuthenticatedUser(
            id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"] or row["username"]),
            role=str(row["role"] or "viewer"),
            data_key=bytes(data_key),
        )
