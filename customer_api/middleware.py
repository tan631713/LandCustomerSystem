"""HTTP middleware installed by the customer API factory."""

from fastapi import Request


def install_mobile_security_headers(app):
    @app.middleware("http")
    async def mobile_security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/mobile"):
            # script-src/style-src additionally allow unpkg.com (Leaflet's
            # JS/CSS); img-src additionally allows wmts.nlsc.gov.tw
            # (內政部國土測繪中心通用電子地圖, the default base map -- free,
            # no API key, better Taiwan road/place-name coverage than
            # OpenStreetMap), *.basemaps.cartocdn.com (CARTO Voyager, the
            # switchable alternate style closer to Google Maps' look), AND
            # unpkg.com itself -- Leaflet's default marker-pin icon is a
            # separate PNG (unpkg.com/leaflet@1.9.4/dist/images/marker-
            # icon.png etc.), not something bundled into leaflet.js/css,
            # so it is its own <img> load subject to img-src. Missing this
            # was a real bug: every marker on the 地圖 page rendered as a
            # broken-image placeholder with Leaflet's hardcoded
            # alt="Marker" text, on every device, because the CSP allowed
            # unpkg.com for script-src/style-src but never for img-src.
            # None of these are XHR/fetch calls, so connect-src is
            # untouched. This mirrors the base-map options the desktop
            # app's own exported map HTML already offers (see
            # customer_productivity.py's build_map_html()), just now
            # reachable from a page this CSP actually governs.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' https://unpkg.com; "
                "style-src 'self' https://unpkg.com; "
                "img-src 'self' data: blob: https://wmts.nlsc.gov.tw "
                "https://*.basemaps.cartocdn.com https://unpkg.com; "
                "connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Permissions-Policy"] = (
                "camera=(), microphone=(), geolocation=(self), payment=()"
            )
            if request.url.path.endswith("service-worker.js"):
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Service-Worker-Allowed"] = "/mobile/"
            elif request.url.path in {
                "/mobile",
                "/mobile/",
                "/mobile/index.html",
                "/mobile/app.js",
                "/mobile/field-visit.js",
            }:
                response.headers["Cache-Control"] = "no-store"
        return response
