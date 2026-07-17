"""Project and project-assignment routes."""

from typing import Annotated
from fastapi import Depends, HTTPException
from customer_api.auth import ApiSession
from customer_api.schemas import ProjectRecordsUpdate, ProjectTaskWrite, ProjectWrite
from customer_api.types import AuthenticatedUser


def register_project_routes(app, *, settings, source, current_session, editor_user):
    @app.get("/api/v1/projects")
    def projects(session: Annotated[ApiSession, Depends(current_session)]):
        return {"items": source.list_projects(session.user)}

    @app.post("/api/v1/projects", status_code=201)
    def create_project(
        payload: ProjectWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            project_id = source.save_project(
                user, payload.title, payload.status, payload.note,
                assigned_to=payload.assigned_to, due_date=payload.due_date,
                priority=payload.priority, next_action=payload.next_action,
                archived=payload.archived,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": project_id}

    @app.put("/api/v1/projects/{project_id}")
    def update_project(
        project_id: int,
        payload: ProjectWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.save_project(
                user,
                payload.title,
                payload.status,
                payload.note,
                project_id,
                assigned_to=payload.assigned_to, due_date=payload.due_date,
                priority=payload.priority, next_action=payload.next_action,
                archived=payload.archived,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到案件。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": saved_id}

    @app.delete("/api/v1/projects/{project_id}", status_code=204)
    def delete_project(
        project_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        if not source.delete_project(user, project_id):
            raise HTTPException(status_code=404, detail="找不到案件。")
        return None

    @app.put("/api/v1/projects/{project_id}/records")
    def update_project_records(
        project_id: int,
        payload: ProjectRecordsUpdate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            if payload.mode == "add":
                processed = source.add_records_to_project(
                    user, project_id, payload.record_ids
                )
            else:
                processed = source.remove_records_from_project(
                    user, project_id, payload.record_ids
                )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="案件或資料不存在。"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"processed": processed}

    @app.put("/api/v1/projects/{project_id}/archive")
    def archive_project(
        project_id: int,
        archived: bool,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            source.archive_project(user, project_id, archived)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到案件。") from exc
        return {"id": project_id, "archived": archived}

    @app.get("/api/v1/project-tasks")
    def project_tasks(
        session: Annotated[ApiSession, Depends(current_session)],
        project_id: int | None = None,
        include_completed: bool = True,
    ):
        return {
            "items": source.list_project_tasks(
                session.user, project_id, include_completed
            )
        }

    @app.post("/api/v1/project-tasks", status_code=201)
    def create_project_task(
        payload: ProjectTaskWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            task_id = source.save_project_task(
                user, payload.project_id, payload.title,
                assignee=payload.assignee, due_date=payload.due_date,
                status=payload.status, priority=payload.priority,
                checklist=payload.checklist,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到案件。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": task_id}

    @app.put("/api/v1/project-tasks/{task_id}")
    def update_project_task(
        task_id: int,
        payload: ProjectTaskWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.save_project_task(
                user, payload.project_id, payload.title,
                assignee=payload.assignee, due_date=payload.due_date,
                status=payload.status, priority=payload.priority,
                checklist=payload.checklist, task_id=task_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到案件或任務。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": saved_id}

    @app.delete("/api/v1/project-tasks/{task_id}", status_code=204)
    def delete_project_task(
        task_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        if not source.delete_project_task(user, task_id):
            raise HTTPException(status_code=404, detail="找不到任務。")
        return None
