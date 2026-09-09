import pytest

from app.services.s3_tenant_assets import (
    S3TenantAssetsError,
    build_tenant_asset_keys,
    build_tenant_logo_asset,
    ensure_tenant_asset_structure,
    upload_tenant_logo,
)


class FakeS3Client:
    def __init__(self):
        self.objects = []

    def put_object(self, **kwargs):
        self.objects.append(kwargs)


def test_build_tenant_asset_keys_uses_default_structure(monkeypatch):
    monkeypatch.delenv("S3_TENANT_ASSETS_ROOT_PREFIX", raising=False)
    monkeypatch.delenv("S3_TENANT_ASSET_FOLDERS", raising=False)

    assert build_tenant_asset_keys("lafiore") == [
        "tenants/lafiore/",
        "tenants/lafiore/banners/",
        "tenants/lafiore/domicilios/",
        "tenants/lafiore/empleados/",
        "tenants/lafiore/logos/",
        "tenants/lafiore/productos/",
    ]


def test_ensure_tenant_asset_structure_creates_s3_folder_markers(monkeypatch):
    monkeypatch.setenv("S3_TENANT_ASSETS_ENABLED", "true")
    monkeypatch.setenv("S3_TENANT_ASSETS_BUCKET", "petalops-assets")
    s3_client = FakeS3Client()

    result = ensure_tenant_asset_structure("lafiore", s3_client=s3_client)

    assert result["enabled"] is True
    assert result["bucket"] == "petalops-assets"
    assert result["prefix"] == "tenants/lafiore/"
    assert [item["Key"] for item in s3_client.objects] == result["createdKeys"]
    assert all(item["Bucket"] == "petalops-assets" for item in s3_client.objects)
    assert all(item["Body"] == b"" for item in s3_client.objects)


def test_ensure_tenant_asset_structure_skips_when_not_configured(monkeypatch):
    monkeypatch.delenv("S3_TENANT_ASSETS_ENABLED", raising=False)
    monkeypatch.delenv("S3_TENANT_ASSETS_BUCKET", raising=False)
    monkeypatch.delenv("AWS_S3_BUCKET", raising=False)
    s3_client = FakeS3Client()

    result = ensure_tenant_asset_structure("lafiore", s3_client=s3_client)

    assert result["enabled"] is False
    assert s3_client.objects == []


def test_ensure_tenant_asset_structure_required_fails_when_not_configured(monkeypatch):
    monkeypatch.delenv("S3_TENANT_ASSETS_ENABLED", raising=False)
    monkeypatch.delenv("S3_TENANT_ASSETS_BUCKET", raising=False)
    monkeypatch.delenv("AWS_S3_BUCKET", raising=False)

    with pytest.raises(S3TenantAssetsError):
        ensure_tenant_asset_structure("lafiore", required=True)


def test_ensure_tenant_asset_structure_uses_aws_region(monkeypatch):
    calls = []
    s3_client = FakeS3Client()

    class FakeBoto3:
        @staticmethod
        def client(service_name, **kwargs):
            calls.append((service_name, kwargs))
            return s3_client

    monkeypatch.setenv("S3_TENANT_ASSETS_ENABLED", "true")
    monkeypatch.setenv("AWS_S3_BUCKET", "petalops-assets")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setitem(__import__("sys").modules, "boto3", FakeBoto3)

    ensure_tenant_asset_structure("lafiore")

    assert calls == [("s3", {"region_name": "us-east-1"})]
    assert s3_client.objects


def test_build_tenant_asset_keys_rejects_nested_slug():
    with pytest.raises(ValueError):
        build_tenant_asset_keys("tenant/otro")


def test_build_tenant_logo_asset_uses_contract_paths(monkeypatch):
    monkeypatch.delenv("S3_LOGO_BUCKET", raising=False)
    monkeypatch.delenv("S3_LOGO_CLOUDFRONT_URL", raising=False)

    asset = build_tenant_logo_asset("petalops", "Logo Principal.PNG")

    assert asset == {
        "bucket": "petalops-assets",
        "key": "tenants/petalops/logos/logo-principal.png",
        "url": "https://ddy2osi8uorg4.cloudfront.net/tenants/petalops/logos/logo-principal.png",
    }


def test_upload_tenant_logo_rejects_invalid_extension():
    with pytest.raises(ValueError):
        upload_tenant_logo("petalops", "logo.gif", b"fake")


def test_upload_tenant_logo_rejects_files_over_15mb():
    with pytest.raises(ValueError):
        upload_tenant_logo("petalops", "logo.png", b"0" * (15 * 1024 * 1024 + 1))


def test_upload_tenant_logo_puts_object_with_content_type(monkeypatch):
    monkeypatch.delenv("S3_LOGO_BUCKET", raising=False)
    s3_client = FakeS3Client()

    result = upload_tenant_logo("petalops", "logo.webp", b"image-bytes", content_type="image/webp", s3_client=s3_client)

    assert result["key"] == "tenants/petalops/logos/logo.webp"
    assert s3_client.objects == [
        {
            "Bucket": "petalops-assets",
            "Key": "tenants/petalops/logos/logo.webp",
            "Body": b"image-bytes",
            "ContentType": "image/webp",
        }
    ]
