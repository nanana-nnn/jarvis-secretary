import uvicorn

from .config import Settings


def main() -> None:
    settings = Settings.from_env()
    settings.validate_tls()
    uvicorn.run(
        "server.app:app",
        host=settings.host,
        port=settings.port,
        ssl_certfile=str(settings.tls_cert),
        ssl_keyfile=str(settings.tls_key),
    )


if __name__ == "__main__":
    main()
