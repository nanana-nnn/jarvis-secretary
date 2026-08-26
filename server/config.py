from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    tls_cert: Path
    tls_key: Path
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        host = os.getenv("HOST", "127.0.0.1")
        origins = tuple(x.strip() for x in os.getenv("ALLOWED_ORIGINS", "").split(",") if x.strip())
        return cls(
            host=host,
            port=int(os.getenv("PORT", "8787")),
            tls_cert=Path(os.getenv("TLS_CERT", "./certs/lan.crt")),
            tls_key=Path(os.getenv("TLS_KEY", "./certs/lan.key")),
            allowed_origins=origins,
        )

    def validate_tls(self) -> None:
        missing = [str(path) for path in (self.tls_cert, self.tls_key) if not path.is_file()]
        if missing:
            raise RuntimeError("TLS file missing: " + ", ".join(missing) + ". Run scripts/gen-cert.sh first.")
