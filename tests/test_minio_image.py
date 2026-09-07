import gzip
import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts import minio_image

IMAGE_ID = "sha256:" + "a" * 64
REVISION = "b" * 40
IMAGE_DETAILS = {
    "Id": IMAGE_ID,
    "RootFS": {"Layers": ["sha256:" + "d" * 64]},
    "Config": {"User": "10001:10001", "Entrypoint": ["/usr/local/bin/minio"]},
}


@pytest.fixture
def bundle(tmp_path):
    archive = tmp_path / minio_image.ARCHIVE
    archive.write_bytes(b"test archive")
    manifest = {
        "format_version": 1,
        "image_tag": minio_image.IMAGE_TAG,
        "platform": minio_image.PLATFORM,
        "archive": minio_image.ARCHIVE,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "image_id": IMAGE_ID,
        "image_fingerprint": minio_image.image_fingerprint(IMAGE_DETAILS),
        "project_revision": REVISION,
    }
    (tmp_path / minio_image.MANIFEST).write_text(json.dumps(manifest))
    return tmp_path, manifest


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("format_version", 2),
        ("image_tag", "unrelated:latest"),
        ("platform", "linux/arm64"),
        ("archive", "../different-image.tar.gz"),
        ("archive_sha256", "invalid"),
        ("image_id", "invalid"),
        ("image_fingerprint", "invalid"),
        ("project_revision", "main"),
    ],
)
def test_invalid_manifest_never_invokes_docker(bundle, key, value):
    directory, manifest = bundle
    manifest[key] = value
    (directory / minio_image.MANIFEST).write_text(json.dumps(manifest))
    with patch.object(minio_image.subprocess, "run") as run, pytest.raises(ValueError):
        minio_image.load_image(directory)
    run.assert_not_called()


def test_non_object_manifest_rejected():
    with pytest.raises(ValueError, match="Invalid image manifest"):
        minio_image.validate_manifest([])


def test_sha256_file_streams_multiple_chunks_without_file_digest(tmp_path):
    content = b"a" * (minio_image.HASH_CHUNK_SIZE + 17)
    path = tmp_path / "large-enough-to-stream.bin"
    path.write_bytes(content)
    assert minio_image.sha256_file(path) == hashlib.sha256(content).hexdigest()


def test_corrupted_archive_never_invokes_docker(bundle):
    directory, _ = bundle
    (directory / minio_image.ARCHIVE).write_bytes(b"changed")
    with (
        patch.object(minio_image.subprocess, "run") as run,
        pytest.raises(ValueError, match="checksum mismatch"),
    ):
        minio_image.load_image(directory)
    run.assert_not_called()


def test_valid_bundle_loads_only_the_fixed_archive(bundle):
    directory, _ = bundle
    with (
        patch.object(minio_image.subprocess, "run") as run,
        patch.object(minio_image, "image_details", return_value=IMAGE_DETAILS),
    ):
        minio_image.load_image(directory)
    run.assert_called_once_with(
        ["docker", "image", "load", "--input", str(directory / minio_image.ARCHIVE)], check=True
    )


def test_loaded_image_mismatch_is_an_error(bundle):
    directory, _ = bundle
    different = {**IMAGE_DETAILS, "RootFS": {"Layers": ["sha256:" + "e" * 64]}}
    with (
        patch.object(minio_image.subprocess, "run"),
        patch.object(minio_image, "image_details", return_value=different),
        pytest.raises(ValueError, match="image content"),
    ):
        minio_image.load_image(directory)


def test_export_and_load_round_trip(tmp_path):
    directory = tmp_path / "bundle"

    def docker_run(command, **kwargs):
        if command[2] == "save":
            Path(command[4]).write_bytes(b"saved docker image")
        return subprocess.CompletedProcess(command, 0)

    with (
        patch.object(minio_image.subprocess, "run", side_effect=docker_run),
        patch.object(minio_image, "image_details", return_value=IMAGE_DETAILS),
    ):
        minio_image.export_image(directory, REVISION)
        minio_image.load_image(directory)
        with pytest.raises(FileExistsError):
            minio_image.export_image(directory, REVISION)
    with gzip.open(directory / minio_image.ARCHIVE, "rb") as stream:
        assert stream.read() == b"saved docker image"
    assert {p.name for p in directory.iterdir()} == {minio_image.ARCHIVE, minio_image.MANIFEST}


def test_wrong_platform_rejected():
    result = subprocess.CompletedProcess(
        [], 0, stdout=json.dumps([{"Os": "linux", "Architecture": "arm64", "Id": IMAGE_ID}])
    )
    with (
        patch.object(minio_image.subprocess, "run", return_value=result),
        pytest.raises(ValueError, match="linux/amd64"),
    ):
        minio_image.image_details()


def test_export_requires_full_revision_before_invoking_docker(tmp_path):
    with patch.object(minio_image.subprocess, "run") as run, pytest.raises(ValueError):
        minio_image.export_image(tmp_path / "bundle", "main")
    run.assert_not_called()


def test_bundle_tag_matches_compose():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "compose.yaml").read_text())
    assert compose["services"]["minio"]["image"] == minio_image.IMAGE_TAG


def test_different_docker_store_ids_do_not_reject_identical_content(bundle):
    directory, _ = bundle
    different_id = {**IMAGE_DETAILS, "Id": "sha256:" + "c" * 64}
    with (
        patch.object(minio_image.subprocess, "run"),
        patch.object(minio_image, "image_details", return_value=different_id),
    ):
        minio_image.load_image(directory)


@pytest.mark.parametrize("field", ["User", "Entrypoint"])
def test_fingerprint_includes_runtime_configuration(field):
    different = {**IMAGE_DETAILS, "Config": {**IMAGE_DETAILS["Config"], field: "changed"}}
    assert minio_image.image_fingerprint(different) != minio_image.image_fingerprint(IMAGE_DETAILS)


def test_fingerprint_normalizes_missing_and_empty_optional_configuration():
    explicit_defaults = {
        **IMAGE_DETAILS,
        "Config": {**IMAGE_DETAILS["Config"], "Cmd": [], "Labels": {}, "StopSignal": "SIGTERM"},
    }
    assert minio_image.image_fingerprint(explicit_defaults) == minio_image.image_fingerprint(
        IMAGE_DETAILS
    )
