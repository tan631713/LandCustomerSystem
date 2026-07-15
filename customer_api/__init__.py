"""Local FastAPI service for desktop and mobile clients."""

from customer_api.app import create_app
from customer_api.config import ApiSettings

__all__ = ["ApiSettings", "create_app"]
