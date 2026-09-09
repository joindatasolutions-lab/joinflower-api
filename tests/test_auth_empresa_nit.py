from app.routers.auth import _build_unique_empresa_nit


class _FakeDb:
    def __init__(self, existing):
        self.existing = {str(item).lower() for item in existing}

    def execute(self, _statement, params=None):
        nit = str((params or {}).get("nit") or "").lower()
        return _FakeResult(nit in self.existing)


class _FakeResult:
    def __init__(self, exists):
        self.exists = exists

    def first(self):
        return (1,) if self.exists else None


def test_build_unique_empresa_nit_uses_slug_fallback_when_default_exists():
    db = _FakeDb(existing={"NIT-12"})

    assert _build_unique_empresa_nit(db, 12, "La Fiore") == "NIT-LAFIORE-12"


def test_build_unique_empresa_nit_adds_suffix_when_slug_fallback_exists():
    db = _FakeDb(existing={"NIT-12", "NIT-LAFIORE-12"})

    assert _build_unique_empresa_nit(db, 12, "La Fiore") == "NIT-LAFIORE-12-2"
