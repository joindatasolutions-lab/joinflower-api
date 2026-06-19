from app.services.domicilio_service import is_store_pickup_tipo_entrega


def test_store_pickup_tipo_entrega_variants_are_detected():
    assert is_store_pickup_tipo_entrega("recogida_en_tienda") is True
    assert is_store_pickup_tipo_entrega("Recoger en tienda") is True
    assert is_store_pickup_tipo_entrega("tienda") is True
    assert is_store_pickup_tipo_entrega("retiro-en-tienda") is True


def test_delivery_tipo_entrega_is_not_store_pickup():
    assert is_store_pickup_tipo_entrega("DOMICILIO") is False
    assert is_store_pickup_tipo_entrega("") is False
    assert is_store_pickup_tipo_entrega(None) is False
