"""Authenticated owner-contact endpoints used by the Windows client."""

from fastapi import Depends, HTTPException, Query

from customer_api.owner_contact_schemas import (
    OwnerContactCreate,
    OwnerContactDeactivate,
    OwnerContactDuplicateCheck,
    OwnerContactLink,
    OwnerContactReactivate,
    OwnerContactUpdate,
)
from customer_api.owner_contact_service import (
    OwnerContactConflict,
    OwnerContactError,
    OwnerContactNotFound,
)


def _owner_contact_error(exc):
    if isinstance(exc, OwnerContactNotFound):
        status, code = 404, "owner_contact_not_found"
    elif isinstance(exc, OwnerContactConflict):
        status, code = 409, "owner_contact_conflict"
    elif isinstance(exc, OwnerContactError):
        status, code = 400, "owner_contact_invalid"
    else:
        raise exc
    raise HTTPException(
        status_code=status,
        detail={"code": code, "message": str(exc)},
    ) from exc


def register_owner_contact_routes(
    app, *, settings, source, current_session, editor_user
):
    del settings

    @app.get("/api/v1/records/{record_id}/owner-contacts")
    def list_owner_contacts(
        record_id: int,
        include_inactive: bool = False,
        session=Depends(current_session),
    ):
        try:
            return source.list_owner_contacts(
                session.user, record_id, include_inactive=include_inactive
            )
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.get("/api/v1/records/{record_id}/owner-contacts/{relation_id}")
    def owner_contact_detail(
        record_id: int,
        relation_id: int,
        session=Depends(current_session),
    ):
        try:
            return {
                "item": source.get_owner_contact_relation(
                    session.user, record_id, relation_id
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.get("/api/v1/contacts/search")
    @app.get("/api/v1/owner-contacts/search", include_in_schema=False)
    def search_owner_contacts(
        q: str = Query(min_length=1, max_length=200),
        limit: int = Query(default=50, ge=1, le=50),
        session=Depends(current_session),
    ):
        query = str(q or "").strip()
        if not query:
            return {"items": []}
        return {
            "items": source.search_owner_contacts(
                session.user, query, limit=limit
            )
        }

    @app.get("/api/v1/owner-contacts/duplicates", include_in_schema=False)
    def owner_contact_duplicates(
        name: str = Query(default="", max_length=100),
        mobile_phone: str = Query(default="", max_length=30),
        home_phone: str = Query(default="", max_length=30),
        registered_address: str = Query(default="", max_length=500),
        contact_address: str = Query(default="", max_length=500),
        limit: int = Query(default=20, ge=1, le=50),
        session=Depends(current_session),
    ):
        return {
            "items": source.find_owner_contact_duplicates(
                session.user,
                name=name,
                mobile_phone=mobile_phone,
                home_phone=home_phone,
                registered_address=registered_address,
                contact_address=contact_address,
                limit=limit,
            )
        }

    @app.post("/api/v1/contacts/duplicate-check")
    def owner_contact_duplicate_check(
        payload: OwnerContactDuplicateCheck,
        session=Depends(current_session),
    ):
        return {
            "items": source.find_owner_contact_duplicates(
                session.user,
                **payload.model_dump(),
            )
        }

    @app.post("/api/v1/records/{record_id}/owner-contacts", status_code=201)
    def create_owner_contact(
        record_id: int,
        payload: OwnerContactCreate,
        user=Depends(editor_user),
    ):
        try:
            return {
                "item": source.create_owner_contact(
                    user, record_id, payload.model_dump(mode="json")
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.post(
        "/api/v1/records/{record_id}/owner-contacts/link", status_code=201
    )
    def link_owner_contact(
        record_id: int,
        payload: OwnerContactLink,
        user=Depends(editor_user),
    ):
        try:
            return {
                "item": source.link_owner_contact(
                    user, record_id, payload.model_dump(mode="json")
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.put("/api/v1/records/{record_id}/owner-contacts/{relation_id}")
    def update_owner_contact(
        record_id: int,
        relation_id: int,
        payload: OwnerContactUpdate,
        user=Depends(editor_user),
    ):
        try:
            return {
                "item": source.update_owner_contact(
                    user,
                    record_id,
                    relation_id,
                    payload.model_dump(mode="json"),
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.post(
        "/api/v1/records/{record_id}/owner-contacts/{relation_id}/deactivate"
    )
    def deactivate_owner_contact(
        record_id: int,
        relation_id: int,
        payload: OwnerContactDeactivate | None = None,
        user=Depends(editor_user),
    ):
        try:
            return {
                "item": source.deactivate_owner_contact(
                    user,
                    record_id,
                    relation_id,
                    payload.model_dump(mode="json") if payload else {},
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.post(
        "/api/v1/records/{record_id}/owner-contacts/{relation_id}/reactivate"
    )
    def reactivate_owner_contact(
        record_id: int,
        relation_id: int,
        payload: OwnerContactReactivate | None = None,
        user=Depends(editor_user),
    ):
        try:
            return {
                "item": source.reactivate_owner_contact(
                    user,
                    record_id,
                    relation_id,
                    payload.model_dump(mode="json") if payload else {},
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.get("/api/v1/owners/{owner_id}/contacts")
    def list_owner_contacts_by_owner(
        owner_id: int,
        include_inactive: bool = False,
        session=Depends(current_session),
    ):
        try:
            return source.list_owner_contacts_by_owner(
                session.user,
                owner_id,
                include_inactive=include_inactive,
            )
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.get("/api/v1/owners/{owner_id}/contacts/{relation_id}")
    def owner_contact_detail_by_owner(
        owner_id: int,
        relation_id: int,
        session=Depends(current_session),
    ):
        try:
            return {
                "item": source.get_owner_contact_relation_by_owner(
                    session.user, owner_id, relation_id
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.post("/api/v1/owners/{owner_id}/contacts", status_code=201)
    def create_owner_contact_by_owner(
        owner_id: int,
        payload: OwnerContactCreate,
        user=Depends(editor_user),
    ):
        try:
            return {
                "item": source.create_owner_contact_by_owner(
                    user, owner_id, payload.model_dump(mode="json")
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.post("/api/v1/owners/{owner_id}/contacts/link", status_code=201)
    def link_owner_contact_by_owner(
        owner_id: int,
        payload: OwnerContactLink,
        user=Depends(editor_user),
    ):
        try:
            return {
                "item": source.link_owner_contact_by_owner(
                    user, owner_id, payload.model_dump(mode="json")
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.put("/api/v1/owners/{owner_id}/contacts/{relation_id}")
    def update_owner_contact_by_owner(
        owner_id: int,
        relation_id: int,
        payload: OwnerContactUpdate,
        user=Depends(editor_user),
    ):
        try:
            return {
                "item": source.update_owner_contact_by_owner(
                    user,
                    owner_id,
                    relation_id,
                    payload.model_dump(mode="json"),
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.post(
        "/api/v1/owners/{owner_id}/contacts/{relation_id}/deactivate"
    )
    def deactivate_owner_contact_by_owner(
        owner_id: int,
        relation_id: int,
        payload: OwnerContactDeactivate | None = None,
        user=Depends(editor_user),
    ):
        try:
            return {
                "item": source.deactivate_owner_contact_by_owner(
                    user,
                    owner_id,
                    relation_id,
                    payload.model_dump(mode="json") if payload else {},
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)

    @app.post(
        "/api/v1/owners/{owner_id}/contacts/{relation_id}/reactivate"
    )
    def reactivate_owner_contact_by_owner(
        owner_id: int,
        relation_id: int,
        payload: OwnerContactReactivate | None = None,
        user=Depends(editor_user),
    ):
        try:
            return {
                "item": source.reactivate_owner_contact_by_owner(
                    user,
                    owner_id,
                    relation_id,
                    payload.model_dump(mode="json") if payload else {},
                )
            }
        except OwnerContactError as exc:
            _owner_contact_error(exc)
