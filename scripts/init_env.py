"""Create local secrets without printing them or overwriting an existing file."""

import os
import secrets
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    values = {}
    for line in (root / ".env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    for key in (
        "DJANGO_SECRET_KEY",
        "JWT_SIGNING_KEY",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "S3_SECRET_KEY",
    ):
        values[key] = secrets.token_hex(32)
    values["REDIS_URL"] = f"redis://:{values['REDIS_PASSWORD']}@redis:6379/0"
    values["REDIS_CACHE_URL"] = f"redis://:{values['REDIS_PASSWORD']}@redis:6379/1"
    path = root / ".env"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(".env already exists; nothing changed.")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("# Local development secrets. Do not commit this file.\n")
        stream.writelines(f"{key}={value}\n" for key, value in values.items())
    print("Created .env with unique development secrets.")


if __name__ == "__main__":
    main()
