from __future__ import annotations

import mimetypes
from pathlib import Path
import shutil
from typing import Union
from urllib.parse import quote

import boto3
from botocore.client import Config as BotoConfig

from config import get_settings


def _client():
    settings = get_settings()
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
        config=BotoConfig(signature_version="s3v4"),
    )


def _bucket_name() -> str:
    return get_settings().s3_bucket_name


def _using_local_storage() -> bool:
    return not get_settings().uses_s3_storage


def _local_storage_root() -> Path:
    root = get_settings().local_storage_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_local_file_path(storage_key: str) -> Path:
    root = _local_storage_root()
    file_path = (root / storage_key).resolve()
    if root != file_path and root not in file_path.parents:
        raise ValueError("Invalid local storage key")
    return file_path


def upload_file(local_path: Union[str, Path], s3_key: str, content_type: str = None) -> str:
    if _using_local_storage():
        destination = get_local_file_path(s3_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, destination)
        return s3_key

    guessed_content_type = content_type or mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
    _client().upload_file(
        str(local_path),
        _bucket_name(),
        s3_key,
        ExtraArgs={"ServerSideEncryption": "AES256", "ContentType": guessed_content_type},
    )
    return s3_key


def download_file(s3_key: str, local_path: Union[str, Path]) -> None:
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    if _using_local_storage():
        shutil.copy2(get_local_file_path(s3_key), local_path)
        return

    _client().download_file(_bucket_name(), s3_key, str(local_path))


def generate_presigned_url(s3_key: str, expiry: int = 3600, filename: str = None) -> str:
    if _using_local_storage():
        base_url = get_settings().backend_public_url.rstrip("/")
        return f"{base_url}/api/files/{quote(s3_key, safe='/')}"

    params = {"Bucket": _bucket_name(), "Key": s3_key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

    return _client().generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expiry,
    )
