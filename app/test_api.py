import urllib.request
import urllib.parse
import json

BASE = "http://127.0.0.1:8001"

# ─── 1. LOGIN ───────────────────────────────────────────
print("=== LOGIN ===")
login_data = json.dumps({
    "login": "joinadmin",
    "password": "Admin123*"
}).encode()

req = urllib.request.Request(
    f"{BASE}/auth/login",
    data=login_data,
    headers={"Content-Type": "application/json"},
    method="POST"
)

try:
    res = urllib.request.urlopen(req, timeout=5)
    data = json.loads(res.read())
    print(f"✅ Respuesta login completa: {data}")  # ← ver todas las keys
    token = data.get("access_token") or data.get("token") or data.get("accessToken")
    if not token:
        print(f"❌ No se encontró token en la respuesta. Keys disponibles: {list(data.keys())}")
        exit()
    print(f"✅ Token obtenido: {token[:40]}...")
except urllib.error.HTTPError as e:
    print(f"❌ Login falló {e.code}: {e.read().decode()}")
    exit()

# ─── 2. PROBAR /pedidos ──────────────────────────────────
print("\n=== GET /pedidos ===")
req2 = urllib.request.Request(
    f"{BASE}/pedidos?empresaID=1&sucursalID=1&page=1&pageSize=20",
    headers={"Authorization": f"Bearer {token}"},
    method="GET"
)

try:
    res2 = urllib.request.urlopen(req2, timeout=5)
    data2 = json.loads(res2.read())
    print(f"✅ Respuesta: {json.dumps(data2, indent=2)[:500]}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"❌ Error {e.code}: {body}")