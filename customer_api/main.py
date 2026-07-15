"""ASGI entrypoint used by uvicorn and FastAPI tooling."""

from customer_api.app import create_app


app = create_app()
