"""Shared API data types."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str
    display_name: str
    role: str
    data_key: bytes = field(repr=False)
