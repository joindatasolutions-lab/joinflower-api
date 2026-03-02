from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.producto import Producto

router = APIRouter()


@router.get("/catalogo/{empresa_id}")
def obtener_catalogo(empresa_id: int, db: Session = Depends(get_db)):

    productos = (
        db.query(Producto)
        .options(joinedload(Producto.categoria))
        .filter(
            Producto.activo == True,
            Producto.empresaID == empresa_id
        )
        .order_by(Producto.ordenCatalogo.asc())
        .all()
    )

    return [
        {
            "idProducto": p.idProducto,
            "nombreProducto": p.nombreProducto,
            "precio": float(p.precioBase),
            "imagenUrl": p.imagenUrl,
            "esDestacado": p.esDestacado,
            "ordenCatalogo": p.ordenCatalogo,
            "nombreCategoria": p.categoria.nombreCategoria if p.categoria else None
        }
        for p in productos
    ]