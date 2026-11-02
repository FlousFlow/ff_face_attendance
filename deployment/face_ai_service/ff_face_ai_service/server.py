"""Run the private face API with optional local TLS for the Odoo pairing flow."""

import os

import uvicorn


def main():
    uvicorn.run(
        "ff_face_ai_service.main:app",
        host=os.getenv("FF_LISTEN_HOST", "127.0.0.1"),
        port=int(os.getenv("FF_LISTEN_PORT", "8787")),
        workers=1,
        ssl_certfile=os.getenv("FF_TLS_CERTFILE") or None,
        ssl_keyfile=os.getenv("FF_TLS_KEYFILE") or None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
