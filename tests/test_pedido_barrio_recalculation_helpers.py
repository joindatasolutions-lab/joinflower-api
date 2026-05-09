from app.routers.barrios import _invalidate_barrios_cache
from app.routers.pedido import _normalize_delivery_type_from_barrio_name
from app.services.cache import get_cache, set_cache


def test_normalize_delivery_type_from_barrio_name_returns_store_pickup():
    assert _normalize_delivery_type_from_barrio_name("Recoger en tienda") == "recogida_en_tienda"
    assert _normalize_delivery_type_from_barrio_name(" recoger en tienda ") == "recogida_en_tienda"


def test_normalize_delivery_type_from_barrio_name_returns_delivery_for_regular_neighborhood():
    assert _normalize_delivery_type_from_barrio_name("Adela Char") == "domicilio"
    assert _normalize_delivery_type_from_barrio_name("") == "domicilio"


def test_invalidate_barrios_cache_clears_branch_prefix_entries():
    key_base = "barrios:v2:3:3:__base__"
    key_query = "barrios:v2:3:3:adela"
    key_other_branch = "barrios:v2:3:4:__base__"
    set_cache(key_base, [{"nombreBarrio": "Adela Char"}], ttl=300)
    set_cache(key_query, [{"nombreBarrio": "Adela Char"}], ttl=300)
    set_cache(key_other_branch, [{"nombreBarrio": "Otro"}], ttl=300)

    _invalidate_barrios_cache(empresa_id=3, sucursal_id=3)

    assert get_cache(key_base) is None
    assert get_cache(key_query) is None
    assert get_cache(key_other_branch) is not None
