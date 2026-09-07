"""Export or verify/load the private CI-built MinIO image using only the standard library."""

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IMAGE_TAG = "mini-dms-minio:2025-10-15"
ARCHIVE = "minio-image.tar.gz"
MANIFEST = "manifest.json"
PLATFORM = "linux/amd64"


def sha256_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def image_details():
    result = subprocess.run(
        ["docker", "image", "inspect", IMAGE_TAG], check=True, capture_output=True, text=True
    )
    info = json.loads(result.stdout)[0]
    if f"{info['Os']}/{info['Architecture']}" != PLATFORM:
        raise ValueError(f"This image bundle requires {PLATFORM}.")
    return info


def image_fingerprint(info):
    # Docker's classic and containerd stores may report different IDs for the same import.
    # Compare ordered filesystem-layer digests and normalized runtime configuration instead.
    config = info["Config"]
    runtime = {
        key: config.get(key) or [] for key in ("Env", "Entrypoint", "Cmd", "Shell", "OnBuild")
    }
    runtime.update({key: config.get(key) or "" for key in ("User", "WorkingDir")})
    runtime.update({key: sorted(config.get(key) or {}) for key in ("ExposedPorts", "Volumes")})
    runtime.update({key: config.get(key) or {} for key in ("Labels", "Healthcheck")})
    runtime["StopSignal"] = config.get("StopSignal") or "SIGTERM"
    runtime["ArgsEscaped"] = bool(config.get("ArgsEscaped"))
    payload = {"layers": info["RootFS"]["Layers"], "runtime": runtime}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("Invalid image manifest.")
    for key, expected in {
        "format_version": 1,
        "image_tag": IMAGE_TAG,
        "platform": PLATFORM,
        "archive": ARCHIVE,
    }.items():
        if manifest.get(key) != expected:
            raise ValueError(f"Unexpected manifest field: {key}.")
    for key, pattern in {
        "archive_sha256": r"[0-9a-f]{64}",
        "image_id": r"sha256:[0-9a-f]{64}",
        "image_fingerprint": r"[0-9a-f]{64}",
        "project_revision": r"[0-9a-f]{40}",
    }.items():
        if not re.fullmatch(pattern, str(manifest.get(key, ""))):
            raise ValueError(f"Invalid manifest field: {key}.")


def export_image(directory, revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("A full project commit SHA is required.")
    details = image_details()
    # Never overwrite an existing bundle or include workspace files in the export.
    directory.mkdir(parents=True, exist_ok=False)
    archive = directory / ARCHIVE
    with tempfile.TemporaryDirectory(prefix="dms-image-") as temporary:
        raw = Path(temporary) / "image.tar"
        subprocess.run(["docker", "image", "save", "--output", str(raw), IMAGE_TAG], check=True)
        with raw.open("rb") as source, gzip.open(archive, "wb", compresslevel=6) as target:
            shutil.copyfileobj(source, target)
    manifest = {
        "format_version": 1,
        "image_tag": IMAGE_TAG,
        "image_id": details["Id"],
        "image_fingerprint": image_fingerprint(details),
        "platform": PLATFORM,
        "archive": ARCHIVE,
        "archive_sha256": sha256_file(archive),
        "project_revision": revision,
    }
    validate_manifest(manifest)
    (directory / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {IMAGE_TAG} with SHA-256 {manifest['archive_sha256']}.")


def load_image(directory):
    manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    validate_manifest(manifest)
    archive = directory / ARCHIVE
    if sha256_file(archive) != manifest["archive_sha256"]:
        raise ValueError(
            "Archive checksum mismatch. Nothing was loaded; download the bundle again."
        )
    subprocess.run(["docker", "image", "load", "--input", str(archive)], check=True)
    if image_fingerprint(image_details()) != manifest["image_fingerprint"]:
        raise ValueError(
            "Loaded image content does not match the manifest. Do not start the stack."
        )
    print(f"Verified and loaded {IMAGE_TAG} ({PLATFORM}).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["export", "load"])
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--revision", help="Full project commit SHA; required when exporting")
    args = parser.parse_args()
    try:
        if args.operation == "export":
            if not args.revision:
                parser.error("--revision is required when exporting")
            export_image(args.directory, args.revision)
        else:
            load_image(args.directory)
    except (OSError, ValueError, KeyError, IndexError, subprocess.CalledProcessError) as exc:
        print(f"Image bundle operation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
