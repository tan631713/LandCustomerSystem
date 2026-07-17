"""HTTP middleware installed by the customer API factory."""

from fastapi import Request


def install_mobile_security_headers(app):
    @app.middleware("http")
    async def mobile_security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/mobile"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Permissions-Policy"] = (
                "camera=(), microphone=(), geolocation=(), payment=()"
            )
            if request.url.path.endswith("service-worker.js"):
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Service-Worker-Allowed"] = "/mobile/"
            elif request.url.path in {"/mobile", "/mobile/", "/mobile/index.html"}:
                response.headers["Cache-Control"] = "no-store"
        return response
