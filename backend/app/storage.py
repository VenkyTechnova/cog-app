"""Encrypted document storage (local filesystem or S3-compatible).

Local: files are encrypted with Fernet (AES-128-CBC + HMAC) before touching disk.
S3: objects are written with server-side encryption (SSE-KMS when a key id is configured)
*and* client-side Fernet encryption, so a misconfigured bucket never exposes plaintext.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet

from .config import get_settings


def _fernet() -> Fernet:
    s = get_settings()
    key = s.storage_encryption_key
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(("storage:" + s.secret_key).encode()).digest()).decode()
    return Fernet(key)


class Storage:
    def put(self, key: str, data: bytes) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def get(self, key: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def makedirs(self, prefix: str, subfolders: list[str]) -> None:  # pragma: no cover
        raise NotImplementedError

    def delete(self, key: str) -> None:  # pragma: no cover
        raise NotImplementedError


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("Invalid storage key")
        return p

    def put(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_fernet().encrypt(data))
        os.chmod(p, 0o600)
        return key

    def get(self, key: str) -> bytes:
        return _fernet().decrypt(self._path(key).read_bytes())

    def makedirs(self, prefix: str, subfolders: list[str]) -> None:
        for sf in subfolders:
            d = self._path(f"{prefix}/{sf}")
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()


class S3Storage(Storage):
    def __init__(self):
        import boto3  # optional dependency

        s = get_settings()
        self.bucket = s.s3_bucket
        self.kms = s.s3_kms_key_id
        self.client = boto3.client("s3", endpoint_url=s.s3_endpoint_url or None, region_name=s.aws_region)

    def put(self, key: str, data: bytes) -> str:
        extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms} if self.kms else {"ServerSideEncryption": "AES256"}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=_fernet().encrypt(data), **extra)
        return key

    def get(self, key: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return _fernet().decrypt(obj["Body"].read())

    def makedirs(self, prefix: str, subfolders: list[str]) -> None:
        for sf in subfolders:
            self.client.put_object(Bucket=self.bucket, Key=f"{prefix}/{sf}/", Body=b"")

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = S3Storage() if s.storage_backend == "s3" else LocalStorage(s.storage_path)
    return _storage


def reset_storage(root: str | None = None) -> None:
    global _storage
    _storage = LocalStorage(root) if root else None
