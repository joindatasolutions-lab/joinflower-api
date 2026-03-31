from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
usuarios = [
    ("joinadmin", "Admin123*", 1),
    ("demo1.admin", "Demo1Admin2026*", 1),
    ("demo1.pedidos", "Demo1Pedidos2026*", 1),
    ("demo1.florista1", "Demo1Florista12026*", 1),
    ("demo1.florista2", "Demo1Florista22026*", 1),
    ("demo1.florista3", "Demo1Florista32026*", 1),
    ("demo1.florista4", "Demo1Florista42026*", 1),
    ("demo1.domi1", "Demo1Domi12026*", 1),
    ("demo1.domi2", "Demo1Domi22026*", 1),
    ("demo1.domi3", "Demo1Domi32026*", 1),
    ("demo1.inventario", "Demo1Inventario2026*", 1),
    ("flora.admin", "FloraAdmin2026*", 3),
    ("flora.pedidos", "FloraPedidos2026*", 3),
    ("flora.florista1", "FloraFlorista12026*", 3),
    ("flora.florista2", "FloraFlorista22026*", 3),
    ("flora.florista3", "FloraFlorista32026*", 3),
    ("flora.florista4", "FloraFlorista42026*", 3),
    ("flora.domi1", "FloraDomi12026*", 3),
    ("flora.domi2", "FloraDomi22026*", 3),
    ("flora.domi3", "FloraDomi32026*", 3),
    ("flora.inventario", "FloraInventario2026*", 3),
]
for login, password, empresa_id in usuarios:
    hash = pwd_context.hash(password)
    print(f"-- {login} (empresa {empresa_id})")
    print(f"UPDATE \"petalops\".\"Usuario\" SET \"passwordHash\" = '{hash}' WHERE \"login\" = '{login}' AND \"empresaID\" = {empresa_id};\n")