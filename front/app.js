const outputEl = document.getElementById("output");

const setOutput = (data) => {
  outputEl.textContent =
    typeof data === "string" ? data : JSON.stringify(data, null, 2);
};

const getBaseUrl = () => {
  const value = document.getElementById("apiBase").value.trim();
  return value.endsWith("/") ? value.slice(0, -1) : value;
};

const request = async (path) => {
  const base = getBaseUrl();
  const url = `${base}${path}`;
  setOutput(`Consultando ${url} ...`);

  try {
    const response = await fetch(url, {
      method: "GET",
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

    setOutput({ ok: true, status: response.status, path, body });
  } catch (error) {
    setOutput({
      ok: false,
      path,
      error: "No se pudo conectar al backend. Verifica que este corriendo.",
      detail: String(error),
    });
  }
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
