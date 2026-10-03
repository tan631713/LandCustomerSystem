"""Urban plan (都市計畫) list and land-assignment routes."""

from typing import Annotated

from fastapi import Depends, HTTPException

from customer_api.auth import ApiSession
from customer_api.schemas import UrbanPlanAssignment, UrbanPlanWrite
from customer_api.types import AuthenticatedUser


def register_urban_plan_routes(app, *, settings, source, current_session, editor_user):
    @app.get("/api/v1/urban-plans")
    def urban_plans(session: Annotated[ApiSession, Depends(current_session)]):
        return source.list_urban_plans(session.user)

    @app.post("/api/v1/urban-plans", status_code=201)
    def create_urban_plan(
        payload: UrbanPlanWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            plan_id = source.save_urban_plan(user, payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": plan_id}

    @app.put("/api/v1/urban-plans/assignments")
    def assign_urban_plan(
        payload: UrbanPlanAssignment,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            return source.set_lands_urban_plan(
                user,
                payload.land_ids,
                payload.urban_plan_id,
                payload.only_unassigned,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到土地或都市計畫。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/v1/urban-plans/{plan_id}")
    def update_urban_plan(
        plan_id: int,
        payload: UrbanPlanWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.save_urban_plan(user, payload.name, plan_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到都市計畫。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": saved_id}

    @app.delete("/api/v1/urban-plans/{plan_id}")
    def delete_urban_plan(
        plan_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        result = source.delete_urban_plan(user, plan_id)
        if result is None:
            raise HTTPException(status_code=404, detail="找不到都市計畫。")
        return result
