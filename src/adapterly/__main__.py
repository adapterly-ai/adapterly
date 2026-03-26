"""uvicorn entrypoint: python -m adapterly"""

import uvicorn

from .config import get_settings


def main():
    settings = get_settings()
    uvicorn.run(
        "adapterly.main:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL,
        reload=settings.MODE == "standalone",
    )


if __name__ == "__main__":
    main()
