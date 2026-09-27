"""Environment-driven configuration shared by distributed services."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ServiceConfig:
    sys2_url: str = ""
    sys3_url: str = ""
    request_timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        return cls(
            sys2_url=os.getenv("JALASETU_SYS2_URL", "").rstrip("/"),
            sys3_url=os.getenv("JALASETU_SYS3_URL", "").rstrip("/"),
            request_timeout_seconds=float(os.getenv("JALASETU_REQUEST_TIMEOUT", "120")),
        )
