from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.producto import Producto

router = APIRouter()


def _serializar_catalogo(productos: list[Producto]) -> list[dict]:
    return [
        {
            "idProducto": p.idProducto,
            "nombreProducto": p.nombreProducto,
            "precio": float(p.precioBase),
            "imagenUrl": p.imagenUrl,
            "esDestacado": p.esDestacado,
            "ordenCatalogo": p.ordenCatalogo,
            "nombreCategoria": p.categoria.nombreCategoria if p.categoria else None,
        }
        for p in productos
    ]


@router.get("/catalogo/empresa/{empresa_id}")
def obtener_catalogo_empresa(empresa_id: int, db: Session = Depends(get_db)):

    productos = (
        db.query(Producto)
        .options(joinedload(Producto.categoria))
        .filter(
            Producto.empresaID == empresa_id,
            Producto.activo == 1,
        )
        .order_by(Producto.ordenCatalogo.asc())
        .all()
    )

    return _serializar_catalogo(productos)


@router.get("/catalogo/{empresa_id}")
def obtener_catalogo(empresa_id: int, db: Session = Depends(get_db)):
    # Compatibilidad hacia atras: mantiene el endpoint legado.
    return obtener_catalogo_empresa(empresa_id=empresa_id, db=db)