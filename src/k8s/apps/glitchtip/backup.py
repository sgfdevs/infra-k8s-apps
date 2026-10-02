"""Stream a PostgreSQL snapshot, its referenced S3 blobs, and SECRET_KEY to K8up."""

import hashlib
import io
import json
import os
from pathlib import PurePosixPath
import subprocess
import sys
import tarfile
import tempfile

import boto3
from botocore.config import Config
import psycopg2


def object_path(key):
    path = PurePosixPath(key)
    if not key or path.is_absolute() or ".." in path.parts:
        raise ValueError("Unsafe S3 object key")
    return "uploads/" + key


def database():
    return psycopg2.connect(
        host=os.environ["DATABASE_HOST"],
        port=os.environ["DATABASE_PORT"],
        dbname=os.environ["DATABASE_NAME"],
        user=os.environ["DATABASE_USER"],
        password=os.environ["DATABASE_PASSWORD"],
        sslmode=os.environ.get("PGSSLMODE", "require"),
        application_name="glitchtip-backup",
    )


def postgres_env():
    return {
        **os.environ,
        "PGHOST": os.environ["DATABASE_HOST"],
        "PGPORT": os.environ["DATABASE_PORT"],
        "PGDATABASE": os.environ["DATABASE_NAME"],
        "PGUSER": os.environ["DATABASE_USER"],
        "PGPASSWORD": os.environ["DATABASE_PASSWORD"],
        "PGSSLMODE": os.environ.get("PGSSLMODE", "require"),
    }


class CheckedBody:
    def __init__(self, body):
        self.body = body
        self.digest = hashlib.sha1()

    def read(self, size=-1):
        data = self.body.read(size)
        self.digest.update(data)
        return data


def main():
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["AWS_S3_ENDPOINT_URL"],
        config=Config(s3={"addressing_style": "path"}),
    )
    with database() as connection, tempfile.TemporaryDirectory() as directory:
        connection.set_session(isolation_level="REPEATABLE READ", readonly=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_export_snapshot()")
            snapshot = cursor.fetchone()[0]
            cursor.execute("SELECT blob, size, checksum FROM files_fileblob WHERE blob <> ''")
            objects = [
                {"key": key, "size": size, "sha1": checksum}
                for key, size, checksum in cursor.fetchall()
            ]
        for item in objects:
            object_path(item["key"])
        dump = directory + "/glitchtip.dump"
        subprocess.run(
            [
                "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
                "--snapshot=" + snapshot, "--file=" + dump,
            ],
            env=postgres_env(),
            check=True,
        )
        with open(dump, "rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        metadata = {
            "format": 1,
            "applicationVersion": os.environ["GLITCHTIP_VERSION"],
            "secretKey": os.environ["SECRET_KEY"],
            "databaseSha256": digest,
            "objects": objects,
        }
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
            data = json.dumps(metadata).encode()
            info = tarfile.TarInfo("metadata.json")
            info.size = len(data)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(data))
            archive.add(dump, arcname="glitchtip.dump")
            for item in objects:
                response = s3.get_object(
                    Bucket=os.environ["AWS_STORAGE_BUCKET_NAME"], Key=item["key"]
                )
                if item["size"] is not None and response["ContentLength"] != item["size"]:
                    raise ValueError("S3 blob size does not match the database snapshot")
                info = tarfile.TarInfo(object_path(item["key"]))
                info.size = response["ContentLength"]
                info.mode = 0o600
                body = CheckedBody(response["Body"])
                try:
                    archive.addfile(info, body)
                finally:
                    response["Body"].close()
                if body.digest.hexdigest() != item["sha1"]:
                    raise ValueError("S3 blob checksum does not match the database snapshot")


if __name__ == "__main__":
    main()
