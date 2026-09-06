"""Create a private development bucket and a bucket-scoped application identity."""

import json
import os
import subprocess
import tempfile


def mc(*args):
    try:
        subprocess.run(["mc", *args], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "Storage initialization failed. Check the endpoint, bucket and configured credentials."
        ) from None


def main():
    bucket = os.environ["S3_BUCKET"]
    # Never invoke a shell or interpolate a user-controlled command string.
    mc(
        "alias",
        "set",
        "local",
        os.environ["S3_ENDPOINT_URL"],
        os.environ["MINIO_ROOT_USER"],
        os.environ["MINIO_ROOT_PASSWORD"],
    )
    mc("mb", "--ignore-existing", f"local/{bucket}")
    mc("anonymous", "set", "none", f"local/{bucket}")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                ],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            },
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as stream:
        json.dump(policy, stream)
        stream.flush()
        mc("admin", "policy", "create", "local", "dms-bucket", stream.name)
    mc("admin", "user", "add", "local", os.environ["S3_ACCESS_KEY"], os.environ["S3_SECRET_KEY"])
    mc("admin", "policy", "attach", "local", "dms-bucket", "--user", os.environ["S3_ACCESS_KEY"])
    print("Private bucket and scoped application identity are ready.")


if __name__ == "__main__":
    main()
