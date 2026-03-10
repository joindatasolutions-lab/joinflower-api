const outputEl = document.getElementById("output");

const setOutput = (data) => {
  outputEl.textContent =
    typeof data === "string" ? data : JSON.stringify(data, null, 2);
};

const formatDateTime = (value) => {
  if (!value) {
    return "-";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return parsed.toLocaleString("es-CO", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const renderPedidosSummary = (payload) => {
  const items = payload?.items || [];
  const table = items.map((item) => ({
    numeroPedido: item.numeroPedido,
    codigoPedido: item.codigoPedido || "-",
    cliente: item.cliente,
    empresaID: item.empresaID || "-",
    sucursalID: item.sucursalID || "-",
    estado: item.estado,
    fechaEntrega: formatDateTime(item.fechaEntrega),
    franjaEntrega: item.horaEntrega || "-",
    total: item.total,
  }));

  setOutput({
    ok: true,
    total: payload?.total || 0,
    page: payload?.page,
    pageSize: payload?.pageSize,
    pedidos: table,
  });
};

const getBaseUrl = () => {
  const value = document.getElementById("apiBase").value.trim();
  return value.endsWith("/") ? value.slice(0, -1) : value;
};

const request = async (path, method = "GET") => {
  const base = getBaseUrl();
  const url = `${base}${path}`;
  setOutput(`Consultando ${method} ${url} ...`);

  try {
    const response = await fetch(url, {
      method,
      headers: {
        Accept: "application/json",
      },
    });

    const isJson = response.headers
      .get("content-type")
      ?.includes("application/json");

    const body = isJson ? await response.json() : await response.text();

    if (!response.ok) {
      setOutput({
        ok: false,
        status: response.status,
        path,
        body,
      });
      return;
    }

    setOutput({ ok: true, status: response.status, method, path, body });
  } catch (error) {
    setOutput({
      ok: false,
      path,
      method,
      error: "No se pudo conectar al backend. Verifica que este corriendo.",
      detail: String(error),
    });
  }
};

const getTodayIso = () => new Date().toISOString().slice(0, 10);

const buildProduccionQuery = () => {
  const empresa = document.getElementById("empresaProduccion").value.trim() || "1";
  const sucursal = document.getElementById("sucursalProduccion").value.trim();
  const fecha = document.getElementById("fechaProduccion").value || getTodayIso();

  const qs = new URLSearchParams({
    empresaID: empresa,
    fecha,
    autoAsignarPendientesHoy: "true",
  });
  if (sucursal) {
    qs.set("sucursalID", sucursal);
  }
  return qs.toString();
};

document.getElementById("btnPing").addEventListener("click", () => {
  request("/ping");
});

document.getElementById("btnHealth").addEventListener("click", () => {
  request("/health");
});

document.getElementById("btnCatalogo").addEventListener("click", () => {
  const empresa = document.getElementById("empresaCatalogo").value.trim() || "1";
  request(`/catalogo/${empresa}`);
});

document.getElementById("btnBarrios").addEventListener("click", () => {
  const empresa = document.getElementById("empresaBarrio").value.trim() || "1";
  const sucursal = document.getElementById("sucursalBarrio").value.trim() || "1";
  const q = encodeURIComponent(
    document.getElementById("queryBarrio").value.trim() || "ce"
  );

  request(`/barrios/search?q=${q}&empresa_id=${empresa}&sucursal_id=${sucursal}`);
});

document.getElementById("btnCliente").addEventListener("click", () => {
  const empresa = document.getElementById("empresaCliente").value.trim() || "1";
  const ident = encodeURIComponent(
    document.getElementById("identCliente").value.trim() || "123456"
  );

  request(`/cliente/buscar/${empresa}/${ident}`);
});

document.getElementById("btnProduccionModulo").addEventListener("click", () => {
  request(`/produccion?${buildProduccionQuery()}`);
});

document.getElementById("btnAsignarHoyManual").addEventListener("click", () => {
  const empresa = document.getElementById("empresaProduccion").value.trim() || "1";
  const sucursal = document.getElementById("sucursalProduccion").value.trim();
  const qs = new URLSearchParams({ empresaID: empresa });
  if (sucursal) {
    qs.set("sucursalID", sucursal);
  }
  request(`/produccion/asignar-pendientes-hoy?${qs.toString()}`, "POST");
});

document.getElementById("btnPedidos").addEventListener("click", async () => {
  const empresa = document.getElementById("empresaPedidos").value.trim() || "1";
  const sucursal = document.getElementById("sucursalPedidos").value.trim();

  const qs = new URLSearchParams({
    empresaID: empresa,
    page: "1",
    pageSize: "20",
  });
  if (sucursal) {
    qs.set("sucursalID", sucursal);
  }

  const base = getBaseUrl();
  const path = `/pedidos?${qs.toString()}`;
  const url = `${base}${path}`;
  setOutput(`Consultando GET ${url} ...`);

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    const body = await response.json();
    if (!response.ok) {
      setOutput({ ok: false, status: response.status, path, body });
      return;
    }
    renderPedidosSummary(body);
  } catch (error) {
    setOutput({
      ok: false,
      path,
      error: "No se pudo consultar pedidos.",
      detail: String(error),
    });
  }
});

document.getElementById("fechaProduccion").value = getTodayIso();
