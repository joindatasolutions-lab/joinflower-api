# Script para borrar todos los registros de empresaID=3 excepto la tabla Empresa
from app.database import SessionLocal
from sqlalchemy import text

def borrar_empresa(empresa_id: int = 3):
    tablas = [
        'PedidoDetalle', 'Pedido', 'Producto', 'Pago', 'Entrega', 'Cliente', 'Barrio', 'Categoria',
        'Domiciliario', 'Empleado', 'Florista', 'Insumo', 'Inventario', 'MovimientoInventario', 'Sucursal', 'Produccion'
    ]
    db = SessionLocal()
    try:
        for tabla in tablas:
            print(f"Borrando de {tabla}...")
            db.execute(text(f"DELETE FROM {tabla} WHERE empresaID = :empresa_id"), {"empresa_id": empresa_id})
        db.commit()
        print("Borrado completado para empresaID=3.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    borrar_empresa(3)
