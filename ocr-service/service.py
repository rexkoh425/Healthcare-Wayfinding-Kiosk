import logging, logging.config, sys

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        }
    },
    "handlers": {
        "stderr": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "formatter": "plain",
            "level": "DEBUG",
        },
    },
    "root": {
        "level": "WARNING",
        "handlers": ["stderr"],
    },
    "loggers": {
        "ocr": {
            "level": "DEBUG",
            "handlers": ["stderr"],
            "propagate": False,
        },
        "picamera2": {"level": "WARNING"},
        "libcamera": {"level": "WARNING"},
        "uvicorn": {"level": "WARNING"},
        "uvicorn.error": {"level": "WARNING"},
        "uvicorn.access": {"level": "WARNING"},
    },
}

logging.config.dictConfig(LOGGING)
log = logging.getLogger("ocr")
log.debug("ocr logger ready")


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import ocr

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def _startup():
    log.info("startup event fired")

app.include_router(ocr.router)

