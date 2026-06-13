from datetime import date
from decimal import Decimal
from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


def _parse_front_date(value):
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return value


def _parse_front_money(value):
    if value is None or isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    raw = str(value).strip()
    if not raw:
        return Decimal("0")

    cleaned = (
        raw.replace("$", "")
        .replace("COP", "")
        .replace("cop", "")
        .replace(" ", "")
    )

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            cleaned = "".join(parts)
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            cleaned = "".join(parts)
        else:
            cleaned = cleaned.replace(",", ".")

    return Decimal(cleaned)


class CajaDiaItem(BaseModel):
    fecha_operacion: date
    base_inicial: Decimal
    efectivo_ventas: Decimal
    total_gastos: Decimal
    total_efectivo: Decimal
    monto_guardado: Decimal
    nueva_base: Decimal
    observacion: str | None = None


class CajaListResponse(BaseModel):
    items: list[CajaDiaItem]


class CajaEfectivoDiaResponse(BaseModel):
    empresaID: int
    sucursalID: int
    fecha: date
    efectivo: Decimal
    totalEfectivo: Decimal


class CajaCierreRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    empresaID: int = Field(validation_alias=AliasChoices("empresaID", "empresa_id"), gt=0)
    sucursalID: int = Field(validation_alias=AliasChoices("sucursalID", "sucursal_id"), gt=0)
    fechaOperacion: date = Field(validation_alias=AliasChoices("fechaOperacion", "fecha_operacion", "fecha"))
    baseInicial: Decimal = Field(
        default=Decimal("0"),
        validation_alias=AliasChoices("baseInicial", "base_inicial", "base"),
        ge=Decimal("0"),
    )
    efectivo: Decimal = Field(
        default=Decimal("0"),
        validation_alias=AliasChoices("efectivo", "efectivoVentas", "efectivo_ventas"),
        ge=Decimal("0"),
    )
    gasto: Decimal = Field(
        default=Decimal("0"),
        validation_alias=AliasChoices("gasto", "totalGastos", "total_gastos"),
        ge=Decimal("0"),
    )
    totalEfectivo: Decimal = Field(
        default=Decimal("0"),
        validation_alias=AliasChoices("totalEfectivo", "total_efectivo", "tEfectivo", "t_efectivo"),
        ge=Decimal("0"),
    )
    montoGuardado: Decimal = Field(
        default=Decimal("0"),
        validation_alias=AliasChoices("montoGuardado", "monto_guardado", "guardado"),
        ge=Decimal("0"),
    )
    nuevaBase: Decimal = Field(
        default=Decimal("0"),
        validation_alias=AliasChoices("nuevaBase", "nueva_base"),
        ge=Decimal("0"),
    )
    observacion: str | None = Field(default=None, max_length=1000)
    usuarioID: int | None = Field(
        default=None,
        validation_alias=AliasChoices("usuarioID", "usuario_id"),
        gt=0,
    )

    @field_validator("fechaOperacion", mode="before")
    @classmethod
    def parse_fecha_operacion(cls, value):
        return _parse_front_date(value)

    @field_validator(
        "baseInicial",
        "efectivo",
        "gasto",
        "totalEfectivo",
        "montoGuardado",
        "nuevaBase",
        mode="before",
    )
    @classmethod
    def parse_money_fields(cls, value):
        return _parse_front_money(value)


class CajaCierreResponse(BaseModel):
    status: str
    item: CajaDiaItem
