"""FastAPI application factory for local desktop/mobile synchronization."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles

from customer_api.auth import LoginThrottle, SessionStore
from customer_api.config import ApiSettings
from customer_api.data_sources import CustomerDataSource, create_data_source
from customer_api.dependencies import build_auth_dependencies
from customer_api.middleware import install_mobile_security_headers
from customer_api.routes_attachments import register_attachment_routes
from customer_api.routes_contacts import register_contact_routes
from customer_api.routes_core import register_core_routes
from customer_api.routes_desktop_features import register_desktop_feature_routes
from customer_api.routes_followups import register_followup_routes
from customer_api.routes_projects import register_project_routes
from customer_api.routes_records import register_record_routes
from customer_api.routes_tags import register_tag_routes
from customer_api.routes_views import register_view_routes
from customer_version import APP_VERSION


MOBILE_WEB_DIRECTORY = Path(__file__).resolve().parent.parent / "customer_mobile_web"

def create_app(
    settings: ApiSettings | None = None,
    data_source: CustomerDataSource | None = None,
    session_store: SessionStore | None = None,
    login_throttle: LoginThrottle | None = None,
):
    settings = settings or ApiSettings.from_env()
    source = data_source or create_data_source(settings)
    sessions = session_store or SessionStore(settings.session_ttl_seconds)
    throttle = login_throttle or LoginThrottle()
    bearer = HTTPBearer(auto_error=False)

    app = FastAPI(
        title="土地資料系統 API",
        description="自架 Windows／iPhone 共用資料介面",
        version=APP_VERSION,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.data_source = source
    app.state.sessions = sessions

    install_mobile_security_headers(app)
    current_session, editor_user = build_auth_dependencies(sessions, bearer)

    register_core_routes(
        app,
        source=source,
        sessions=sessions,
        throttle=throttle,
        bearer=bearer,
        current_session=current_session,
    )
    register_record_routes(
        app,
        settings=settings,
        source=source,
        current_session=current_session,
        editor_user=editor_user,
    )
    for registrar in (
        register_contact_routes,
        register_followup_routes,
        register_project_routes,
        register_tag_routes,
        register_desktop_feature_routes,
    ):
        registrar(
            app,
            settings=settings,
            source=source,
            current_session=current_session,
            editor_user=editor_user,
        )
    register_attachment_routes(
        app,
        settings=settings,
        source=source,
        current_session=current_session,
        editor_user=editor_user,
    )
    register_view_routes(app, settings=settings, source=source, current_session=current_session)

    if MOBILE_WEB_DIRECTORY.is_dir():
        app.mount(
            "/mobile",
            StaticFiles(directory=MOBILE_WEB_DIRECTORY, html=True),
            name="mobile",
        )

    return app
