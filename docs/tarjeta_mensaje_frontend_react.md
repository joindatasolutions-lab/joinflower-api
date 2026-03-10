# Integracion Frontend React: Ver mensaje / Imprimir tarjeta

Este documento contiene snippets listos para integrar en el frontend React (`Petalops`).

## 1) Boton en lista de pedidos (solo estado Aprobado)

```jsx
// Ejemplo dentro de la columna Acciones en la tabla de pedidos
{String(pedido.estado || '').toUpperCase() === 'APROBADO' && (
  <button
    type="button"
    className="btn-mensaje-tarjeta"
    onClick={() => onOpenTarjeta(pedido)}
  >
    Ver mensaje / Imprimir tarjeta
  </button>
)}
```

## 2) Llamada al backend

```jsx
async function fetchMensajeTarjeta(pedidoId, token) {
  const resp = await fetch(`/entregas/pedido/${pedidoId}/mensaje`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || 'No se pudo obtener el mensaje de la tarjeta');
  }

  return resp.json();
}
```

## 3) Componente TarjetaMensaje.jsx

```jsx
import { useMemo, useState } from 'react';
import './TarjetaMensaje.css';

const DEFAULT_STYLE = {
  fontFamily: 'Georgia, serif',
  fontSize: 24,
  color: '#1f2937',
  textAlign: 'center',
};

export default function TarjetaMensaje({ open, data, floristName = 'Flora Tienda de Flores', onClose }) {
  const [fontFamily, setFontFamily] = useState(DEFAULT_STYLE.fontFamily);
  const [fontSize, setFontSize] = useState(DEFAULT_STYLE.fontSize);
  const [color, setColor] = useState(DEFAULT_STYLE.color);
  const [textAlign, setTextAlign] = useState(DEFAULT_STYLE.textAlign);

  const textStyle = useMemo(
    () => ({ fontFamily, fontSize: `${fontSize}px`, color, textAlign }),
    [fontFamily, fontSize, color, textAlign]
  );

  if (!open) return null;

  return (
    <div className="tm-overlay" role="dialog" aria-modal="true">
      <div className="tm-modal no-print">
        <h3>Tarjeta de mensaje floral</h3>

        <div className="tm-controls">
          <label>
            Fuente
            <select value={fontFamily} onChange={(e) => setFontFamily(e.target.value)}>
              <option value="Georgia, serif">Georgia</option>
              <option value="'Times New Roman', serif">Times New Roman</option>
              <option value="'Trebuchet MS', sans-serif">Trebuchet MS</option>
              <option value="'Courier New', monospace">Courier New</option>
            </select>
          </label>

          <label>
            Tamano
            <input
              type="range"
              min={14}
              max={48}
              step={1}
              value={fontSize}
              onChange={(e) => setFontSize(Number(e.target.value))}
            />
            <span>{fontSize}px</span>
          </label>

          <label>
            Color
            <input type="color" value={color} onChange={(e) => setColor(e.target.value)} />
          </label>

          <label>
            Alineacion
            <select value={textAlign} onChange={(e) => setTextAlign(e.target.value)}>
              <option value="left">Izquierda</option>
              <option value="center">Centro</option>
              <option value="right">Derecha</option>
            </select>
          </label>
        </div>

        <div className="tm-actions">
          <button type="button" onClick={() => window.print()}>Imprimir tarjeta</button>
          <button type="button" onClick={onClose}>Cerrar</button>
        </div>
      </div>

      <section className="tarjeta-print" aria-label="Tarjeta imprimible">
        <p className="tarjeta-destinatario" style={textStyle}>
          Para: {data?.destinatario || 'Sin destinatario'}
        </p>

        <p className="tarjeta-mensaje" style={textStyle}>
          "{data?.mensaje || 'Sin mensaje'}"
        </p>

        <p className="tarjeta-floristeria">{floristName}</p>
      </section>
    </div>
  );
}
```

## 4) CSS de impresion (TarjetaMensaje.css)

```css
.tm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: grid;
  place-items: center;
  z-index: 1000;
  padding: 16px;
}

.tm-modal {
  width: min(760px, 95vw);
  background: #fff;
  border-radius: 14px;
  padding: 16px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.25);
}

.tm-controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin: 12px 0;
}

.tm-controls label {
  display: grid;
  gap: 6px;
  font-size: 13px;
}

.tm-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 12px;
}

.tarjeta-print {
  width: min(700px, 100%);
  background: #fff;
  border: 1px solid #d1d5db;
  border-radius: 12px;
  padding: 32px 28px;
  margin-top: 12px;
}

.tarjeta-destinatario,
.tarjeta-mensaje {
  margin: 0 0 16px;
  white-space: pre-wrap;
}

.tarjeta-floristeria {
  margin: 24px 0 0;
  text-align: center;
  color: #4b5563;
  font-size: 14px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

@media print {
  body * {
    visibility: hidden;
  }

  .tarjeta-print,
  .tarjeta-print * {
    visibility: visible;
  }

  .tarjeta-print {
    position: absolute;
    inset: 0;
    width: 100%;
    border: none;
    border-radius: 0;
    margin: 0;
    padding: 32mm 18mm;
    box-shadow: none;
  }

  .no-print {
    display: none !important;
  }
}
```

## 5) Ejemplo de integracion en una pagina de pedidos

```jsx
import { useState } from 'react';
import TarjetaMensaje from './TarjetaMensaje';

function PedidosPage({ pedidos, token }) {
  const [tarjetaOpen, setTarjetaOpen] = useState(false);
  const [tarjetaData, setTarjetaData] = useState(null);

  async function onOpenTarjeta(pedido) {
    try {
      const data = await fetchMensajeTarjeta(pedido.pedidoID, token);
      setTarjetaData(data);
      setTarjetaOpen(true);
    } catch (err) {
      alert(err.message);
    }
  }

  return (
    <>
      {pedidos.map((pedido) => (
        <div key={pedido.pedidoID}>
          <span>{pedido.codigoPedido || pedido.numeroPedido}</span>
          {String(pedido.estado || '').toUpperCase() === 'APROBADO' && (
            <button onClick={() => onOpenTarjeta(pedido)}>
              Ver mensaje / Imprimir tarjeta
            </button>
          )}
        </div>
      ))}

      <TarjetaMensaje
        open={tarjetaOpen}
        data={tarjetaData}
        floristName="Flora Tienda de Flores"
        onClose={() => setTarjetaOpen(false)}
      />
    </>
  );
}
```
