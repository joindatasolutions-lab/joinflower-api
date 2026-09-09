from __future__ import annotations

import os
import re
from pathlib import Path

from app.core.logger import get_logger

logger = get_logger("s3_tenant_assets")

DEFAULT_TENANT_ASSET_FOLDERS = ("banners", "domicilios", "empleados", "logos", "productos")
DEFAULT_LOGO_BUCKET = "petalops-assets"
DEFAULT_LOGO_CLOUDFRONT_URL = "https://ddy2osi8uorg4.cloudfront.net"
ALLOWED_LOGO_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "heif"}
MAX_LOGO_BYTES = 15 * 1024 * 1024


class S3TenantAssetsError(RuntimeError):
    pass


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _tenant_assets_enabled() -> bool:
    raw = os.getenv("S3_TENANT_ASSETS_ENABLED")
    if raw is not None:
        return _truthy(raw)
    return bool(os.getenv("S3_TENANT_ASSETS_BUCKET") or os.getenv("AWS_S3_BUCKET"))


def _bucket_name() -> str:
    return str(os.getenv("S3_TENANT_ASSETS_BUCKET") or os.getenv("AWS_S3_BUCKET") or "").strip()


def _root_prefix() -> str:
    return str(os.getenv("S3_TENANT_ASSETS_ROOT_PREFIX", "tenants")).strip("/")


def _aws_region() -> str | None:
    value = str(os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "").strip()
    return value or None


def _s3_client(s3_client=None):
    if s3_client is not None:
        return s3_client
    try:
        import boto3
    except ImportError as exc:
        raise S3TenantAssetsError("boto3 no esta instalado; agrega la dependencia para crear carpetas S3") from exc
    region_name = _aws_region()
    return boto3.client("s3", region_name=region_name) if region_name else boto3.client("s3")


def _asset_folders() -> tuple[str, ...]:
    raw = os.getenv("S3_TENANT_ASSET_FOLDERS", "")
    if not raw.strip():
        return DEFAULT_TENANT_ASSET_FOLDERS

    folders: list[str] = []
    seen: set[str] = set()
    for value in raw.split(","):
        folder = value.strip().strip("/")
        if not folder or folder in seen:
            continue
        seen.add(folder)
        folders.append(folder)
    return tuple(folders or DEFAULT_TENANT_ASSET_FOLDERS)


def build_tenant_asset_keys(tenant_slug: str) -> list[str]:
    slug = str(tenant_slug or "").strip().strip("/")
    if not slug or "/" in slug:
        raise ValueError("tenant_slug debe ser un segmento de ruta S3 valido")

    base_prefix = f"{_root_prefix()}/{slug}".strip("/")
    return [f"{base_prefix}/", *[f"{base_prefix}/{folder}/" for folder in _asset_folders()]]


def ensure_tenant_asset_structure(tenant_slug: str, s3_client=None, required: bool = False) -> dict[str, object]:
    if not _tenant_assets_enabled():
        if required:
            raise S3TenantAssetsError("S3_TENANT_ASSETS_BUCKET o AWS_S3_BUCKET no esta configurado")
        return {"enabled": False, "bucket": None, "prefix": None, "createdKeys": []}

    bucket = _bucket_name()
    if not bucket:
        raise S3TenantAssetsError("S3_TENANT_ASSETS_BUCKET no esta configurado")

    s3_client = _s3_client(s3_client)

    keys = build_tenant_asset_keys(tenant_slug)
    try:
        for key in keys:
            s3_client.put_object(Bucket=bucket, Key=key, Body=b"")
    except Exception as exc:
        logger.error("Error creando estructura S3 para tenant %s", tenant_slug, exc_info=True)
        raise S3TenantAssetsError("No fue posible crear la estructura S3 del tenant") from exc

    return {
        "enabled": True,
        "bucket": bucket,
        "prefix": keys[0],
        "createdKeys": keys,
    }


def sanitize_logo_filename(filename: str | None) -> str:
    raw_name = Path(str(filename or "logo")).name.strip()
    stem = Path(raw_name).stem.strip().lower()
    suffix = Path(raw_name).suffix.lower().lstrip(".")
    if suffix not in ALLOWED_LOGO_EXTENSIONS:
        raise ValueError("file debe ser jpg, jpeg, png, webp, heic o heif")

    safe_stem = re.sub(r"[^a-z0-9._-]+", "-", stem).strip(".-_")
    if not safe_stem:
        safe_stem = "logo"
    return f"{safe_stem[:120]}.{suffix}"


def build_tenant_logo_asset(slug: str, filename: str) -> dict[str, str]:
    tenant_slug = str(slug or "").strip().strip("/")
    if not tenant_slug or "/" in tenant_slug:
        raise ValueError("slug debe ser un segmento de ruta S3 valido")

    safe_filename = sanitize_logo_filename(filename)
    key = f"tenants/{tenant_slug}/logos/{safe_filename}"
    cloudfront_base = str(os.getenv("S3_LOGO_CLOUDFRONT_URL") or DEFAULT_LOGO_CLOUDFRONT_URL).rstrip("/")
    return {
        "bucket": str(os.getenv("S3_LOGO_BUCKET") or DEFAULT_LOGO_BUCKET).strip(),
        "key": key,
        "url": f"{cloudfront_base}/{key}",
    }


def upload_tenant_logo(slug: str, filename: str, body: bytes, content_type: str | None = None, s3_client=None) -> dict[str, str]:
    if len(body) > MAX_LOGO_BYTES:
        raise ValueError("file no puede superar 15MB")

    asset = build_tenant_logo_asset(slug, filename)
    bucket = asset["bucket"]
    if not bucket:
        raise S3TenantAssetsError("S3_LOGO_BUCKET no esta configurado")

    put_kwargs = {
        "Bucket": bucket,
        "Key": asset["key"],
        "Body": body,
    }
    if content_type:
        put_kwargs["ContentType"] = content_type

    try:
        _s3_client(s3_client).put_object(**put_kwargs)
    except Exception as exc:
        logger.error("Error subiendo logo para tenant %s", slug, exc_info=True)
        raise S3TenantAssetsError("No fue posible subir el logo del tenant") from exc

    return asset
