"""Validate a backup and restore it only after explicit operator confirmation."""

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

import boto3
from botocore.config import Config

from backup import database, object_path, postgres_env


def validate(archive, directory):
    members = archive.getmembers()
    names = [member.name for member in members]
    if len(set(names)) != len(names) or any(not member.isfile() for member in members):
        raise ValueError("Duplicate or non-regular archive member")
    metadata = json.load(archive.extractfile("metadata.json"))
    if metadata["format"] != 1:
        raise ValueError("Unsupported backup format")
    if metadata["applicationVersion"] != os.environ["GLITCHTIP_VERSION"]:
        raise ValueError("Restore with the application version recorded in the backup")
    if not hmac.compare_digest(metadata["secretKey"], os.environ["SECRET_KEY"]):
        raise ValueError("SECRET_KEY differs. Recover the original key before restoring.")
    expected = {"metadata.json", "glitchtip.dump"}
    expected.update(object_path(item["key"]) for item in metadata["objects"])
    if set(names) != expected:
        raise ValueError("Unexpected or missing archive members")
    archive.extractall(directory, filter="data")
    with open(Path(directory) / "glitchtip.dump", "rb") as dump:
        if hashlib.file_digest(dump, "sha256").hexdigest() != metadata["databaseSha256"]:
            raise ValueError("Database dump checksum mismatch")
    for item in metadata["objects"]:
        path = Path(directory) / object_path(item["key"])
        with path.open("rb") as blob:
            if hashlib.file_digest(blob, "sha1").hexdigest() != item["sha1"]:
                raise ValueError("S3 blob checksum mismatch")
        if item["size"] is not None and path.stat().st_size != item["size"]:
            raise ValueError("S3 blob size mismatch")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    if not args.check_only and args.confirm != "RESTORE glitchtip":
        parser.error('Supply --confirm "RESTORE glitchtip" to replace the database')
    with tempfile.TemporaryDirectory() as directory:
        with tarfile.open(args.archive) as archive:
            metadata = validate(archive, directory)
        if args.check_only:
            print("Backup format, application key, and checksums verified.")
            return
        with database() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND usename = current_user "
                "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
            )
            if cursor.fetchone()[0]:
                raise RuntimeError("Application or backup connections remain. Stop them first.")
        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ["AWS_S3_ENDPOINT_URL"],
            config=Config(s3={"addressing_style": "path"}),
        )
        # Restore blobs first. Leave newer, unreferenced objects alone.
        for item in metadata["objects"]:
            s3.upload_file(
                str(Path(directory) / object_path(item["key"])),
                os.environ["AWS_STORAGE_BUCKET_NAME"],
                item["key"],
            )
        subprocess.run(
            [
                "pg_restore", "--clean", "--if-exists", "--no-owner",
                "--no-privileges", "--exit-on-error", "--single-transaction",
                "--dbname=" + os.environ["DATABASE_NAME"],
                str(Path(directory) / "glitchtip.dump"),
            ],
            env=postgres_env(),
            check=True,
        )
    print("Restore complete. Run migrations before resuming the application.")


if __name__ == "__main__":
    main()
