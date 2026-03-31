from app.database import SessionLocal
from app.models.usuario import Usuario
from app.models.empresa import Empresa
from app.models.rol import Rol
from app.core.security import pwd_context

# IDs de empresa y rol según los seeds actuales
users = [
    ("flora.admin", "FloraAdmin2026*", 3, 52),
    ("flora.pedidos", "FloraPedidos2026*", 3, 53),
    ("flora.florista1", "FloraFlorista12026*", 3, 54),
    ("flora.domi1", "FloraDomi12026*", 3, 55),
    ("flora.inventario", "FloraInventario2026*", 3, 56),
]

def main():
    db = SessionLocal()
    try:
        for login, password, empresa, rol in users:
            db.query(Usuario).filter_by(login=login).delete()
            db.add(
                Usuario(
                    login=login,
                    passwordHash=pwd_context.hash(password),
                    empresaID=empresa,
                    rolID=rol,
                    estado="Activo",
                    sucursalID=1,
                    nombre=login,
                    email=f"{login}@empresa3.local",
                    createdAt=None,
                    updatedAt=None,
                )
            )
        db.commit()
        print("Usuarios de test actualizados correctamente.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
