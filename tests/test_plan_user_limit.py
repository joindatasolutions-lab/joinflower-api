"""Verifica _plan_user_limit: el limite de usuarios activos por empresa. Por defecto se
calcula por plan (compartido entre empresas), pero petalops.empresa.limite_usuarios permite
un override puntual para una sola empresa sin afectar a las demas del mismo plan.
"""
from app.routers.auth import _plan_user_limit


def test_limite_por_defecto_para_plan_desconocido_o_sin_plan():
    assert _plan_user_limit(None) == 20
    assert _plan_user_limit(0) == 20


def test_limite_por_plan_conocido():
    assert _plan_user_limit(1) == 20
    assert _plan_user_limit(2) == 80
    assert _plan_user_limit(3) == 250


def test_override_de_empresa_gana_sobre_el_plan():
    # Aunque el plan de esta empresa (o la ausencia de plan) daria 20, el override la sube a 30.
    assert _plan_user_limit(None, empresa_override=30) == 30
    assert _plan_user_limit(1, empresa_override=30) == 30


def test_override_de_empresa_no_afecta_otras_llamadas_sin_override():
    # Dos empresas del mismo plan: una con override, otra sin -- cada llamada es independiente.
    assert _plan_user_limit(1, empresa_override=30) == 30
    assert _plan_user_limit(1, empresa_override=None) == 20


def test_override_minimo_es_uno():
    assert _plan_user_limit(1, empresa_override=0) == 1
