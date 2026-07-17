"""Authenticated routes for full desktop-client workflows."""

from datetime import date
from typing import Annotated

from fastapi import Depends, HTTPException, Query

from customer_api.auth import ApiSession
from customer_api.schemas import (
    IdList,
    InsertUndoCreate,
    MergeRecordsWrite,
    NotificationMark,
    PasswordChange,
    PasswordReset,
    RecordUndoCreate,
    ServerBackupMaintenance,
    ServerBackupRequest,
    ServerBackupRestore,
    ServerBackupTargetSync,
    ServerBackupTargetWrite,
    UserCreate,
    UserUpdate,
)
from customer_api.types import AuthenticatedUser


def _admin(user):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="這個操作只允許管理員執行。")
    return user


def register_remote_operation_routes(
    app, *, settings, source, current_session, editor_user
):
    @app.get("/api/v1/recycle-bin")
    def recycle_bin(
        session: Annotated[ApiSession, Depends(current_session)],
        limit: int = Query(default=1000, ge=1, le=5000),
    ):
        return {"items": source.list_recycle_bin(session.user, limit)}

    @app.post("/api/v1/recycle-bin/restore")
    def restore_recycle_bin(
        payload: IdList,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        return {"record_ids": source.restore_recycle_items(user, payload.ids)}

    @app.post("/api/v1/recycle-bin/purge")
    def purge_recycle_bin(
        payload: IdList,
        session: Annotated[ApiSession, Depends(current_session)],
        purge_all: bool = False,
    ):
        user = _admin(session.user)
        return {
            "count": source.purge_recycle_items(
                user, None if purge_all else payload.ids
            )
        }

    @app.get("/api/v1/undo-operations")
    def undo_operations(
        session: Annotated[ApiSession, Depends(current_session)],
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        return {"items": source.list_undo_operations(session.user, limit)}

    @app.post("/api/v1/undo-operations/snapshot", status_code=201)
    def record_undo(
        payload: RecordUndoCreate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        undo_id = source.record_customer_undo(
            user, payload.operation_type, payload.ids, payload.summary
        )
        return {"id": undo_id}

    @app.post("/api/v1/undo-operations/insert", status_code=201)
    def record_insert_undo(
        payload: InsertUndoCreate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        undo_id = source.record_insert_undo(
            user, payload.operation_type, payload.ids, payload.summary
        )
        return {"id": undo_id}

    @app.post("/api/v1/undo-operations/{operation_id}/apply")
    def apply_undo(
        operation_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            result = source.undo_operation(user, operation_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="找不到可復原的操作。")
        return result

    @app.post("/api/v1/records/merge")
    def merge_records(
        payload: MergeRecordsWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            record_id = source.merge_records(
                user,
                payload.primary_id,
                payload.secondary_id,
                payload.values.normalized_values(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到要合併的資料。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": record_id}

    @app.post("/api/v1/notifications/refresh")
    def refresh_notifications(
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        return {"count": source.refresh_notifications(user, date.today().isoformat())}

    @app.get("/api/v1/notifications")
    def notifications(
        session: Annotated[ApiSession, Depends(current_session)],
        include_read: bool = False,
        limit: int = Query(default=500, ge=1, le=1000),
    ):
        return {
            "items": source.list_notifications(
                session.user, include_read=include_read, limit=limit
            )
        }

    @app.put("/api/v1/notifications")
    def mark_notifications(
        payload: NotificationMark,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        return {
            "count": source.mark_notifications(
                user, payload.notification_ids, payload.action
            )
        }

    @app.get("/api/v1/users")
    def users(session: Annotated[ApiSession, Depends(current_session)]):
        user = _admin(session.user)
        return {"items": source.list_users(user)}

    @app.post("/api/v1/users", status_code=201)
    def create_user(
        payload: UserCreate,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        user = _admin(session.user)
        try:
            user_id = source.create_user(
                user, payload.username, payload.password, payload.role,
                payload.display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            if "unique" in str(exc).casefold():
                raise HTTPException(status_code=409, detail="帳號已存在。") from exc
            raise
        return {"id": user_id}

    @app.put("/api/v1/users/{user_id}")
    def update_user(
        user_id: int,
        payload: UserUpdate,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        user = _admin(session.user)
        try:
            saved_id = source.update_user(
                user, user_id, **payload.model_dump()
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到使用者。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": saved_id}

    @app.put("/api/v1/users/{user_id}/password")
    def reset_user_password(
        user_id: int,
        payload: PasswordReset,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        user = _admin(session.user)
        try:
            source.reset_user_password(user, user_id, payload.new_password)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到使用者。") from exc
        return {"id": user_id}

    @app.put("/api/v1/auth/password")
    def change_password(
        payload: PasswordChange,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        try:
            source.change_password(
                session.user, payload.current_password, payload.new_password
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"changed": True}

    @app.post("/api/v1/maintenance/encrypt-existing-records")
    def encrypt_existing_records(
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        user = _admin(session.user)
        safety_backup = ""
        if source.backend_name == "postgresql":
            from backup_postgresql import create_backup

            try:
                safety_backup = str(
                    create_backup(label="pre-encrypt").get("backup_path") or ""
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"加密前安全備份失敗，未變更資料：{exc}",
                ) from exc
        result = source.encrypt_existing_records(user)
        return {**result, "safety_backup": safety_backup}

    @app.get("/api/v1/server-backups/status")
    def server_backup_status(
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        _admin(session.user)
        from backup_postgresql import backup_status

        return {**backup_status(), "database": source.health()}

    @app.get("/api/v1/server-backups")
    def list_server_backups(
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        _admin(session.user)
        if source.backend_name != "postgresql":
            return {"items": []}
        from backup_postgresql import backup_inventory

        return {"items": backup_inventory()}

    @app.post("/api/v1/server-backups", status_code=201)
    def create_server_backup(
        payload: ServerBackupRequest,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        _admin(session.user)
        from backup_postgresql import create_backup

        try:
            return create_backup(
                label=payload.label,
                retention_days=payload.retention_days,
                max_count=payload.max_count,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"伺服器備份失敗：{exc}") from exc

    @app.post("/api/v1/server-backups/maintenance")
    def maintain_server_backups(
        payload: ServerBackupMaintenance,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        _admin(session.user)
        from backup_postgresql import backup_status, prune_backups

        try:
            deleted = prune_backups(
                retention_days=payload.retention_days,
                max_count=payload.max_count,
            )
            return {
                **backup_status(), "database": source.health(),
                "deleted_count": len(deleted),
                "deleted_files": [path.name for path in deleted],
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"伺服器備份整理失敗：{exc}") from exc

    @app.post("/api/v1/server-backups/restore")
    def restore_server_backup(
        payload: ServerBackupRestore,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        _admin(session.user)
        if source.backend_name != "postgresql":
            raise HTTPException(status_code=409, detail="只有 PostgreSQL 家中伺服器可執行還原。")
        from backup_postgresql import restore_backup

        try:
            result = restore_backup(
                payload.backup_name, confirmation=payload.confirmation
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"伺服器還原失敗：{exc}") from exc
        result["revoked_sessions"] = app.state.sessions.revoke_all()
        return result

    @app.get("/api/v1/server-backup-targets")
    def list_server_backup_targets(
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        user = _admin(session.user)
        return {"items": source.list_server_backup_targets(user)}

    def save_backup_target(payload, session, target_id=None):
        user = _admin(session.user)
        from backup_postgresql import validate_backup_target_path

        try:
            resolved = validate_backup_target_path(payload.directory_path)
            saved_id = source.save_server_backup_target(
                user,
                payload.name,
                str(resolved),
                payload.enabled,
                target_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到異地備份目的地。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            if "unique" in str(exc).casefold():
                raise HTTPException(status_code=409, detail="異地備份名稱已存在。") from exc
            raise
        return {"id": saved_id}

    @app.post("/api/v1/server-backup-targets", status_code=201)
    def create_server_backup_target(
        payload: ServerBackupTargetWrite,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        return save_backup_target(payload, session)

    @app.put("/api/v1/server-backup-targets/{target_id}")
    def update_server_backup_target(
        target_id: int,
        payload: ServerBackupTargetWrite,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        return save_backup_target(payload, session, target_id)

    @app.delete("/api/v1/server-backup-targets/{target_id}")
    def delete_server_backup_target(
        target_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        user = _admin(session.user)
        if not source.delete_server_backup_target(user, target_id):
            raise HTTPException(status_code=404, detail="找不到異地備份目的地。")
        return {"deleted": True}

    @app.post("/api/v1/server-backup-targets/sync")
    def sync_server_backup_targets(
        payload: ServerBackupTargetSync,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        user = _admin(session.user)
        if source.backend_name != "postgresql":
            raise HTTPException(status_code=409, detail="只有 PostgreSQL 家中伺服器可同步異地備份。")
        from backup_postgresql import sync_backup_targets

        targets = source.list_server_backup_targets(user)
        try:
            result = sync_backup_targets(
                targets,
                retention_days=payload.retention_days,
                max_count=payload.max_count,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"異地備份失敗：{exc}") from exc
        for item in result.get("results") or []:
            source.update_server_backup_target_result(
                user,
                item["id"],
                item.get("error") if item.get("status") != "success" else None,
            )
        return result
