"""PostgreSQL external and managed attachment workflows."""

import hashlib
import mimetypes
import shutil
import uuid
from pathlib import Path

from customer_api.data_source_base import _row_dict


class PostgreSQLAttachmentMixin:
    def list_attachments(self, user, record_id):
        del user
        record_id = int(record_id)
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            rows = conn.execute(
                """
                SELECT id, ownership_id AS customer_id, file_path, description,
                       storage_path, original_name, media_type, sha256, size_bytes,
                       status, version, created_at
                FROM attachments
                WHERE ownership_id = %s
                ORDER BY id DESC
                """,
                (record_id,),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def get_attachment(self, user, record_id, attachment_id):
        rows = self.list_attachments(user, record_id)
        return next(
            (row for row in rows if int(row["id"]) == int(attachment_id)), None
        )

    @staticmethod
    def _record_attachment_links(conn, record_id):
        row = conn.execute(
            "SELECT owner_id, land_id FROM ownerships WHERE id = %s",
            (int(record_id),),
        ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return int(row["owner_id"]), int(row["land_id"])

    def add_external_attachment(self, user, record_id, file_path, description=""):
        record_id = int(record_id)
        file_path = str(file_path or "").strip()
        if not file_path:
            raise ValueError("附件路徑不可空白")
        original_name = Path(file_path).name or "attachment"
        media_type = mimetypes.guess_type(original_name)[0]
        with self._connect() as conn:
            owner_id, land_id = self._record_attachment_links(conn, record_id)
            row = conn.execute(
                """
                INSERT INTO attachments (
                    ownership_id, owner_id, land_id, file_path, storage_path,
                    original_name, description, media_type, status, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'external', %s)
                RETURNING id
                """,
                (
                    record_id,
                    owner_id,
                    land_id,
                    file_path,
                    file_path,
                    original_name,
                    str(description or "").strip() or None,
                    media_type,
                    user.id,
                ),
            ).fetchone()
            attachment_id = int(row["id"])
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_create_external_attachment', 'attachment', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    attachment_id,
                    f"Created external attachment for ownership {record_id}",
                ),
            )
        return attachment_id

    def import_managed_attachment(
        self,
        user,
        record_id,
        source_path,
        original_name,
        description="",
        media_type="",
    ):
        record_id = int(record_id)
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"找不到附件檔案：{source}")
        safe_name = Path(str(original_name or source.name)).name or "attachment"
        suffix = Path(safe_name).suffix[:20]
        storage_root = self.settings.attachment_directory.resolve()
        customer_directory = storage_root / str(record_id)
        customer_directory.mkdir(parents=True, exist_ok=True)
        destination = customer_directory / f"{uuid.uuid4().hex}{suffix}"
        shutil.copy2(source, destination)
        digest = hashlib.sha256()
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        try:
            with self._connect() as conn:
                owner_id, land_id = self._record_attachment_links(conn, record_id)
                row = conn.execute(
                    """
                    INSERT INTO attachments (
                        ownership_id, owner_id, land_id, file_path, storage_path,
                        original_name, description, media_type, size_bytes,
                        sha256, status, version, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                              'managed', 1, %s)
                    RETURNING id
                    """,
                    (
                        record_id,
                        owner_id,
                        land_id,
                        str(destination),
                        str(destination),
                        safe_name,
                        str(description or "").strip() or None,
                        str(media_type or "").strip()
                        or mimetypes.guess_type(safe_name)[0],
                        destination.stat().st_size,
                        digest.hexdigest(),
                        user.id,
                    ),
                ).fetchone()
                attachment_id = int(row["id"])
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_upload_attachment', 'attachment', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        attachment_id,
                        f"Uploaded attachment for ownership {record_id}",
                    ),
                )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return attachment_id

    def delete_attachment(self, user, record_id, attachment_id):
        record_id = int(record_id)
        attachment_id = int(attachment_id)
        storage_path = ""
        status = ""
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            deleted = conn.execute(
                """
                DELETE FROM attachments
                WHERE id = %s AND ownership_id = %s
                RETURNING storage_path, status
                """,
                (attachment_id, record_id),
            ).fetchone()
            if deleted:
                storage_path = str(deleted.get("storage_path") or "")
                status = str(deleted.get("status") or "")
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_delete_attachment', 'attachment', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        attachment_id,
                        f"Deleted attachment from ownership {record_id}",
                    ),
                )
        if deleted and storage_path and status != "external":
            root = self.settings.attachment_directory.resolve()
            candidate = Path(storage_path).resolve()
            if candidate.is_relative_to(root):
                candidate.unlink(missing_ok=True)
        return bool(deleted)
