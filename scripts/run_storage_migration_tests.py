#!/usr/bin/env python3
"""
Standalone test runner for the shared-bucket storage migration.

This script is intentionally plain Python instead of pytest so it can be run as:

    python scripts/run_storage_migration_tests.py

or, when using the local Docker backend container:

    docker exec cassie-backend python scripts/run_storage_migration_tests.py

Scope:
- backend.api.services.minio_client.MinIOClient
- backend.api.services.kubernetes_manager.KubernetesPipelineRunner._build_init_download_script

The app is large, so this suite focuses on the highest-risk migration surface:
shared bucket storage, legacy bucket fallback reads, presigned URLs, deletion
paths, and Kubernetes init download behavior.
"""

# docker exec cassie-backend python /app/scripts/run_storage_migration_tests.py


from __future__ import annotations

import importlib
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_targets():
    try:
        minio_module = importlib.import_module("backend.api.services.minio_client")
        kubernetes_module = importlib.import_module("backend.api.services.kubernetes_manager")
        from botocore.exceptions import BotoCoreError, ClientError
    except Exception as exc:
        raise RuntimeError(
            "Failed to import backend test targets. "
            "Run this inside the backend container or after installing requirements."
        ) from exc

    return (
        minio_module,
        kubernetes_module,
        minio_module.MinIOClient,
        kubernetes_module.KubernetesPipelineRunner,
        ClientError,
        BotoCoreError,
    )


MINIO_MODULE, K8S_MODULE, MinIOClient, KubernetesPipelineRunner, ClientError, BotoCoreError = _load_targets()


def aws_error(code: str, message: str = "test error", operation: str = "TestOperation") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, operation)


def make_config(
    *,
    endpoint: str = "http://minio:9000",
    public_endpoint: Optional[str] = None,
    access_key: str = "access",
    secret_key: str = "secret",
    region: str = "us-east-1",
    bucket_prefix: str = "cassie-",
) -> SimpleNamespace:
    if public_endpoint is None:
        public_endpoint = endpoint
    return SimpleNamespace(
        minio=SimpleNamespace(
            endpoint=endpoint,
            public_endpoint=public_endpoint,
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            bucket_prefix=bucket_prefix,
        )
    )


class FakePaginator:
    def __init__(self, page_map: Dict[Tuple[str, str], Any]):
        self.page_map = page_map
        self.calls: List[Dict[str, Any]] = []

    def paginate(self, **kwargs):
        self.calls.append(dict(kwargs))
        lookup_key = (kwargs.get("Bucket"), kwargs.get("Prefix"))
        result = self.page_map.get(lookup_key, [])
        if isinstance(result, Exception):
            raise result
        return result


class FakeS3Client:
    def __init__(self):
        self.head_bucket_results: Dict[str, Any] = {}
        self.head_object_results: Dict[Tuple[str, str], Any] = {}
        self.download_results: Dict[Tuple[str, str], Any] = {}
        self.list_pages: Dict[Tuple[str, str], Any] = {}
        self.upload_calls: List[Dict[str, Any]] = []
        self.create_bucket_calls: List[Dict[str, Any]] = []
        self.delete_object_calls: List[Dict[str, Any]] = []
        self.delete_objects_calls: List[Dict[str, Any]] = []
        self.presigned_calls: List[Dict[str, Any]] = []
        self.presigned_url = "https://example.invalid/presigned"
        self.uploaded_payloads: Dict[Tuple[str, str], bytes] = {}
        self.list_buckets_called = 0
        self.paginator = FakePaginator(self.list_pages)

    def list_buckets(self):
        self.list_buckets_called += 1
        return {"Buckets": []}

    def head_bucket(self, Bucket: str):
        result = self.head_bucket_results.get(Bucket)
        if isinstance(result, Exception):
            raise result
        return result if result is not None else {}

    def create_bucket(self, **kwargs):
        self.create_bucket_calls.append(dict(kwargs))
        return {"created": True}

    def upload_file(self, local_path: str, bucket: str, key: str, ExtraArgs: Optional[Dict[str, Any]] = None):
        self.upload_calls.append(
            {"local_path": local_path, "bucket": bucket, "key": key, "extra_args": ExtraArgs or {}}
        )
        self.uploaded_payloads[(bucket, key)] = Path(local_path).read_bytes()

    def download_file(self, bucket: str, key: str, local_path: str):
        result = self.download_results.get((bucket, key), aws_error("NoSuchKey"))
        if isinstance(result, Exception):
            raise result
        payload = result if isinstance(result, bytes) else str(result).encode("utf-8")
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    def get_paginator(self, name: str):
        assert name == "list_objects_v2", f"Unexpected paginator requested: {name}"
        self.paginator = FakePaginator(self.list_pages)
        return self.paginator

    def delete_object(self, **kwargs):
        self.delete_object_calls.append(dict(kwargs))
        self.head_object_results.pop((kwargs["Bucket"], kwargs["Key"]), None)
        return {"Deleted": True}

    def delete_objects(self, **kwargs):
        self.delete_objects_calls.append(dict(kwargs))
        for obj in kwargs.get("Delete", {}).get("Objects", []):
            self.head_object_results.pop((kwargs["Bucket"], obj["Key"]), None)
        return {"Deleted": kwargs.get("Delete", {}).get("Objects", [])}

    def head_object(self, Bucket: str, Key: str):
        result = self.head_object_results.get((Bucket, Key), aws_error("404"))
        if isinstance(result, Exception):
            raise result
        return result

    def generate_presigned_url(self, operation: str, Params: Dict[str, Any], ExpiresIn: int):
        self.presigned_calls.append(
            {"operation": operation, "params": dict(Params), "expires_in": ExpiresIn}
        )
        return self.presigned_url


class FakeBoto3Factory:
    def __init__(self, clients: Optional[List[Any]] = None):
        self.clients = list(clients or [])
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.clients:
            return self.clients.pop(0)
        return FakeS3Client()


def make_client(
    fake_s3: Optional[FakeS3Client] = None,
    *,
    endpoint: str = "http://minio:9000",
    public_endpoint: Optional[str] = None,
    access_key: str = "access",
    secret_key: str = "secret",
    region: str = "us-east-1",
    bucket_prefix: str = "cassie-",
) -> MinIOClient:
    client = MinIOClient(s3_client=fake_s3 or FakeS3Client())
    client._config = make_config(
        endpoint=endpoint,
        public_endpoint=public_endpoint,
        access_key=access_key,
        secret_key=secret_key,
        region=region,
        bucket_prefix=bucket_prefix,
    )
    return client


def assert_equal(actual: Any, expected: Any, message: str = ""):
    if actual != expected:
        raise AssertionError(message or f"Expected {expected!r}, got {actual!r}")


def assert_true(value: Any, message: str = ""):
    if not value:
        raise AssertionError(message or f"Expected truthy value, got {value!r}")


def assert_false(value: Any, message: str = ""):
    if value:
        raise AssertionError(message or f"Expected falsy value, got {value!r}")


def assert_in(needle: str, haystack: str, message: str = ""):
    if needle not in haystack:
        raise AssertionError(message or f"Expected to find {needle!r} in output")


def assert_not_in(needle: str, haystack: str, message: str = ""):
    if needle in haystack:
        raise AssertionError(message or f"Did not expect to find {needle!r} in output")


def assert_raises(exception_type: type[BaseException], func: Callable, *args, **kwargs) -> BaseException:
    try:
        func(*args, **kwargs)
    except exception_type as exc:  # type: ignore[misc]
        return exc
    except Exception as exc:
        raise AssertionError(f"Expected {exception_type.__name__}, got {type(exc).__name__}: {exc}") from exc
    raise AssertionError(f"Expected {exception_type.__name__} to be raised")


def sample_head_response(size: int = 42) -> Dict[str, Any]:
    return {
        "ContentLength": size,
        "LastModified": datetime(2026, 4, 23, 13, 0, 0, tzinfo=timezone.utc),
        "ETag": '"etag-123"',
        "ContentType": "text/plain",
        "Metadata": {"alpha": "beta"},
    }


def test_shared_bucket_name_is_derived_from_bucket_prefix():
    client = make_client(bucket_prefix="cassie-")
    assert_equal(client._get_bucket_name(99), "cassie")


def test_legacy_bucket_name_is_still_available_for_fallback_reads():
    client = make_client(bucket_prefix="cassie-")
    assert_equal(client._get_legacy_bucket_name(7), "cassie-user-7")


def test_object_key_normalization_adds_user_prefix():
    client = make_client()
    assert_equal(client._get_object_key(7, "/jobs/12/output.txt"), "users/7/jobs/12/output.txt")


def test_empty_object_key_maps_to_user_prefix_directory():
    client = make_client()
    assert_equal(client._get_object_key(7, ""), "users/7/")


def test_strip_user_prefix_returns_logical_key():
    client = make_client()
    assert_equal(client._strip_user_prefix(7, "users/7/jobs/12/output.txt"), "jobs/12/output.txt")


def test_read_locations_include_shared_then_legacy():
    client = make_client(bucket_prefix="cassie-")
    locations = client.get_read_locations(7, "jobs/12/output.txt")
    assert_equal(
        locations,
        [
            {"bucket": "cassie", "key": "users/7/jobs/12/output.txt"},
            {"bucket": "cassie-user-7", "key": "jobs/12/output.txt"},
        ],
    )


def test_rewrite_url_base_swaps_scheme_and_host_only():
    client = make_client()
    rewritten = client._rewrite_url_base(
        "http://minio:9000/bucket/key?X-Amz-Signature=abc",
        "https://files.example.com",
    )
    assert_equal(rewritten, "https://files.example.com/bucket/key?X-Amz-Signature=abc")


def test_ensure_user_bucket_reuses_existing_shared_bucket():
    fake_s3 = FakeS3Client()
    fake_s3.head_bucket_results["cassie"] = {}
    client = make_client(fake_s3)
    result = client.ensure_user_bucket(user_id=1)
    assert_equal(result, "cassie")
    assert_equal(fake_s3.create_bucket_calls, [])


def test_ensure_user_bucket_creates_bucket_for_custom_endpoint():
    fake_s3 = FakeS3Client()
    fake_s3.head_bucket_results["cassie"] = aws_error("404")
    client = make_client(fake_s3, endpoint="http://minio:9000", region="us-east-1")
    result = client.ensure_user_bucket(user_id=1)
    assert_equal(result, "cassie")
    assert_equal(fake_s3.create_bucket_calls, [{"Bucket": "cassie"}])


def test_ensure_user_bucket_creates_us_east_1_bucket_without_location_constraint():
    fake_s3 = FakeS3Client()
    fake_s3.head_bucket_results["cassie"] = aws_error("404")
    client = make_client(fake_s3, endpoint="", public_endpoint="", region="us-east-1")
    client.ensure_user_bucket(user_id=1)
    assert_equal(fake_s3.create_bucket_calls, [{"Bucket": "cassie"}])


def test_ensure_user_bucket_creates_regional_bucket_with_location_constraint():
    fake_s3 = FakeS3Client()
    fake_s3.head_bucket_results["cassie"] = aws_error("404")
    client = make_client(fake_s3, endpoint="", public_endpoint="", region="eu-west-1")
    client.ensure_user_bucket(user_id=1)
    assert_equal(
        fake_s3.create_bucket_calls,
        [{"Bucket": "cassie", "CreateBucketConfiguration": {"LocationConstraint": "eu-west-1"}}],
    )


def test_ensure_user_bucket_handles_bucket_already_owned():
    fake_s3 = FakeS3Client()
    fake_s3.head_bucket_results["cassie"] = aws_error("404")

    def create_bucket(**kwargs):
        raise aws_error("BucketAlreadyOwnedByYou")

    fake_s3.create_bucket = create_bucket  # type: ignore[method-assign]
    client = make_client(fake_s3, endpoint="", public_endpoint="", region="eu-west-1")
    assert_equal(client.ensure_user_bucket(user_id=1), "cassie")


def test_upload_file_uses_shared_bucket_and_returns_object_key():
    fake_s3 = FakeS3Client()
    fake_s3.head_bucket_results["cassie"] = {}
    client = make_client(fake_s3)
    with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
        handle.write(b"hello-world")
        temp_path = handle.name
    try:
        result = client.upload_file(5, temp_path, "jobs/12/output.txt", metadata={"kind": "demo"})
        assert_equal(result["bucket"], "cassie")
        assert_equal(result["object_key"], "users/5/jobs/12/output.txt")
        assert_equal(fake_s3.upload_calls[0]["bucket"], "cassie")
        assert_equal(fake_s3.upload_calls[0]["key"], "users/5/jobs/12/output.txt")
        assert_equal(fake_s3.upload_calls[0]["extra_args"], {"Metadata": {"kind": "demo"}})
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_upload_file_rejects_missing_local_file():
    client = make_client(FakeS3Client())
    assert_raises(FileNotFoundError, client.upload_file, 1, "/definitely/missing.txt", "a.txt")


def test_download_file_prefers_shared_location():
    fake_s3 = FakeS3Client()
    fake_s3.download_results[("cassie", "users/7/jobs/12/output.txt")] = b"shared-data"
    client = make_client(fake_s3)
    with tempfile.TemporaryDirectory() as temp_dir:
        destination = str(Path(temp_dir) / "nested" / "output.txt")
        result = client.download_file(7, "jobs/12/output.txt", destination)
        assert_equal(result, destination)
        assert_equal(Path(destination).read_bytes(), b"shared-data")


def test_download_file_falls_back_to_legacy_bucket():
    fake_s3 = FakeS3Client()
    fake_s3.download_results[("cassie", "users/7/jobs/12/output.txt")] = aws_error("NoSuchKey")
    fake_s3.download_results[("cassie-user-7", "jobs/12/output.txt")] = b"legacy-data"
    client = make_client(fake_s3)
    with tempfile.TemporaryDirectory() as temp_dir:
        destination = str(Path(temp_dir) / "output.txt")
        client.download_file(7, "jobs/12/output.txt", destination)
        assert_equal(Path(destination).read_bytes(), b"legacy-data")


def test_download_file_raises_when_missing_in_all_locations():
    fake_s3 = FakeS3Client()
    fake_s3.download_results[("cassie", "users/7/jobs/12/output.txt")] = aws_error("NoSuchKey")
    fake_s3.download_results[("cassie-user-7", "jobs/12/output.txt")] = aws_error("NoSuchKey")
    client = make_client(fake_s3)
    with tempfile.TemporaryDirectory() as temp_dir:
        exc = assert_raises(RuntimeError, client.download_file, 7, "jobs/12/output.txt", str(Path(temp_dir) / "x"))
    assert_in("not found in shared storage", str(exc))


def test_download_file_raises_for_non_recoverable_s3_errors():
    fake_s3 = FakeS3Client()
    fake_s3.download_results[("cassie", "users/7/jobs/12/output.txt")] = aws_error("AccessDenied")
    client = make_client(fake_s3)
    with tempfile.TemporaryDirectory() as temp_dir:
        exc = assert_raises(RuntimeError, client.download_file, 7, "jobs/12/output.txt", str(Path(temp_dir) / "x"))
    assert_in("Failed to download file", str(exc))


def test_list_files_strips_shared_prefix_and_deduplicates_legacy_entries():
    fake_s3 = FakeS3Client()
    ts = datetime(2026, 4, 23, 13, 0, 0, tzinfo=timezone.utc)
    fake_s3.list_pages[("cassie", "users/7/jobs/12")] = [
        {"Contents": [{"Key": "users/7/jobs/12/output.txt", "Size": 12, "LastModified": ts, "ETag": '"etag-a"'}]}
    ]
    fake_s3.list_pages[("cassie-user-7", "jobs/12")] = [
        {"Contents": [{"Key": "jobs/12/output.txt", "Size": 99, "LastModified": ts, "ETag": '"etag-b"'}]}
    ]
    client = make_client(fake_s3)
    files = client.list_files(7, prefix="jobs/12")
    assert_equal(len(files), 1)
    assert_equal(files[0]["key"], "jobs/12/output.txt")
    assert_equal(files[0]["size"], 12)


def test_list_files_returns_empty_when_buckets_are_missing():
    fake_s3 = FakeS3Client()
    fake_s3.list_pages[("cassie", "users/7/jobs")] = aws_error("NoSuchBucket")
    fake_s3.list_pages[("cassie-user-7", "jobs")] = aws_error("NoSuchBucket")
    client = make_client(fake_s3)
    assert_equal(client.list_files(7, prefix="jobs"), [])


def test_delete_file_removes_shared_and_legacy_copies():
    fake_s3 = FakeS3Client()
    fake_s3.head_object_results[("cassie", "users/7/jobs/12/output.txt")] = sample_head_response()
    fake_s3.head_object_results[("cassie-user-7", "jobs/12/output.txt")] = sample_head_response()
    client = make_client(fake_s3)
    deleted = client.delete_file(7, "jobs/12/output.txt")
    assert_true(deleted)
    assert_equal(len(fake_s3.delete_object_calls), 2)


def test_delete_file_returns_false_when_object_does_not_exist():
    client = make_client(FakeS3Client())
    assert_false(client.delete_file(7, "jobs/12/output.txt"))


def test_delete_prefix_counts_objects_across_shared_and_legacy_locations():
    fake_s3 = FakeS3Client()
    fake_s3.list_pages[("cassie", "users/7/jobs/12")] = [
        {"Contents": [{"Key": "users/7/jobs/12/a.txt"}, {"Key": "users/7/jobs/12/b.txt"}]}
    ]
    fake_s3.list_pages[("cassie-user-7", "jobs/12")] = [
        {"Contents": [{"Key": "jobs/12/legacy.txt"}]}
    ]
    client = make_client(fake_s3)
    deleted_count = client.delete_prefix(7, "jobs/12")
    assert_equal(deleted_count, 3)
    assert_equal(len(fake_s3.delete_objects_calls), 2)


def test_generate_presigned_url_uses_existing_shared_location():
    fake_s3 = FakeS3Client()
    fake_s3.head_object_results[("cassie", "users/7/jobs/12/output.txt")] = sample_head_response()
    fake_s3.presigned_url = "https://signed/shared"
    client = make_client(fake_s3)
    url = client.generate_presigned_url(
        7,
        "jobs/12/output.txt",
        response_content_disposition='attachment; filename="output.txt"',
    )
    assert_equal(url, "https://signed/shared")
    params = fake_s3.presigned_calls[0]["params"]
    assert_equal(params["Bucket"], "cassie")
    assert_equal(params["Key"], "users/7/jobs/12/output.txt")
    assert_equal(params["ResponseContentDisposition"], 'attachment; filename="output.txt"')


def test_generate_presigned_url_uses_primary_location_for_new_object():
    fake_s3 = FakeS3Client()
    client = make_client(fake_s3)
    client.generate_presigned_url(7, "jobs/12/new.txt", http_method="PUT")
    call = fake_s3.presigned_calls[0]
    assert_equal(call["operation"], "put_object")
    assert_equal(call["params"]["Bucket"], "cassie")
    assert_equal(call["params"]["Key"], "users/7/jobs/12/new.txt")


def test_generate_presigned_url_uses_public_endpoint_client_when_configured():
    fake_s3 = FakeS3Client()
    fake_s3.head_object_results[("cassie", "users/7/jobs/12/output.txt")] = sample_head_response()
    public_client = FakeS3Client()
    public_client.presigned_url = "https://public.example/signed"
    boto_factory = FakeBoto3Factory([public_client])
    client = make_client(
        fake_s3,
        endpoint="http://minio:9000",
        public_endpoint="https://files.example.com",
    )
    with patch.object(MINIO_MODULE.boto3, "client", boto_factory):
        url = client.generate_presigned_url(7, "jobs/12/output.txt")
    assert_equal(url, "https://public.example/signed")
    assert_equal(boto_factory.calls[0]["endpoint_url"], "https://files.example.com")


def test_file_exists_checks_shared_then_legacy():
    fake_s3 = FakeS3Client()
    fake_s3.head_object_results[("cassie-user-7", "jobs/12/output.txt")] = sample_head_response()
    client = make_client(fake_s3)
    assert_true(client.file_exists(7, "jobs/12/output.txt"))


def test_file_exists_returns_false_on_unexpected_error():
    fake_s3 = FakeS3Client()

    def head_object(**kwargs):
        raise aws_error("AccessDenied")

    fake_s3.head_object = head_object  # type: ignore[method-assign]
    client = make_client(fake_s3)
    assert_false(client.file_exists(7, "jobs/12/output.txt"))


def test_get_file_info_returns_metadata_for_existing_object():
    fake_s3 = FakeS3Client()
    fake_s3.head_object_results[("cassie", "users/7/jobs/12/output.txt")] = sample_head_response(size=77)
    client = make_client(fake_s3)
    info = client.get_file_info(7, "jobs/12/output.txt")
    assert_true(info is not None)
    assert_equal(info["key"], "jobs/12/output.txt")
    assert_equal(info["size"], 77)
    assert_equal(info["metadata"], {"alpha": "beta"})


def test_get_file_info_returns_none_when_file_is_missing():
    client = make_client(FakeS3Client())
    assert_equal(client.get_file_info(7, "jobs/12/output.txt"), None)


def test_create_s3_client_uses_explicit_credentials_when_present():
    created_client = FakeS3Client()
    boto_factory = FakeBoto3Factory([created_client])
    client = MinIOClient(s3_client=None)
    client._config = make_config(endpoint="http://minio:9000", access_key="abc", secret_key="xyz")
    with patch.object(MINIO_MODULE.boto3, "client", boto_factory), patch.object(MINIO_MODULE.time, "sleep", lambda _: None):
        resolved = client._create_s3_client()
    assert_true(resolved is created_client)
    assert_equal(boto_factory.calls[0]["aws_access_key_id"], "abc")
    assert_equal(boto_factory.calls[0]["aws_secret_access_key"], "xyz")
    assert_equal(boto_factory.calls[0]["endpoint_url"], "http://minio:9000")


def test_create_s3_client_uses_default_aws_chain_when_credentials_are_blank():
    created_client = FakeS3Client()
    boto_factory = FakeBoto3Factory([created_client])
    client = MinIOClient(s3_client=None)
    client._config = make_config(endpoint="", public_endpoint="", access_key="", secret_key="")
    with patch.object(MINIO_MODULE.boto3, "client", boto_factory), patch.object(MINIO_MODULE.time, "sleep", lambda _: None):
        client._create_s3_client()
    assert_true("aws_access_key_id" not in boto_factory.calls[0])
    assert_true("aws_secret_access_key" not in boto_factory.calls[0])
    assert_true("endpoint_url" not in boto_factory.calls[0])


def test_build_init_download_script_contains_shared_then_legacy_copy_paths():
    runner = object.__new__(KubernetesPipelineRunner)
    fake_client = make_client(FakeS3Client())
    script = runner._build_init_download_script(
        fake_client,
        42,
        [{"filename": "reads.fastq", "s3_key": "jobs/12/input/reads.fastq"}],
    )
    assert_in('s3://cassie/users/42/jobs/12/input/reads.fastq', script)
    assert_in('s3://cassie-user-42/jobs/12/input/reads.fastq', script)


def test_build_init_download_script_uses_endpoint_guard_and_has_no_break_statements():
    runner = object.__new__(KubernetesPipelineRunner)
    fake_client = make_client(FakeS3Client())
    script = runner._build_init_download_script(
        fake_client,
        42,
        [{"filename": "reads.fastq", "s3_key": "jobs/12/input/reads.fastq"}],
    )
    assert_in('if [ -n "${S3_ENDPOINT:-}" ]; then', script)
    assert_not_in("break", script)


def test_build_init_download_script_escapes_quotes_in_file_names_and_keys():
    runner = object.__new__(KubernetesPipelineRunner)

    class QuotedLocationClient:
        def get_read_locations(self, user_id: int, s3_key: str):
            return [
                {"bucket": 'cassie"shared', "key": 'users/7/jobs/"quoted".txt'},
                {"bucket": 'cassie-user-7', "key": 'jobs/"quoted".txt'},
            ]

    script = runner._build_init_download_script(
        QuotedLocationClient(),
        7,
        [{"filename": 'reads"1".fastq', "s3_key": 'jobs/"quoted".txt'}],
    )
    assert_in('cassie\\"shared', script)
    assert_in('users/7/jobs/\\"quoted\\".txt', script)
    assert_in('/workspace/input/reads\\"1\\".fastq', script)


@dataclass
class TestResult:
    name: str
    success: bool
    details: str = ""


def iter_test_functions() -> Iterable[Tuple[str, Callable[[], None]]]:
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            yield name, value


def run_all_tests() -> List[TestResult]:
    results: List[TestResult] = []
    for name, test_func in iter_test_functions():
        try:
            test_func()
            results.append(TestResult(name=name, success=True))
        except Exception:
            results.append(TestResult(name=name, success=False, details=traceback.format_exc()))
    return results


def print_results(results: List[TestResult]) -> None:
    total = len(results)
    passed = sum(1 for result in results if result.success)
    failed = total - passed

    print("CASSIE Storage Migration Test Suite")
    print("=" * 80)
    print(f"Total: {total}  Passed: {passed}  Failed: {failed}")
    print("=" * 80)

    for result in results:
        status = "PASS" if result.success else "FAIL"
        print(f"[{status}] {result.name}")
        if result.details:
            print(result.details.rstrip())
            print("-" * 80)


def main() -> int:
    results = run_all_tests()
    print_results(results)
    return 0 if all(result.success for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
