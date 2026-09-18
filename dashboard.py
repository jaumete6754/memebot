"""Dashboard web, solo con la libreria estandar.

Es ESTRICTAMENTE DE SOLO LECTURA: no expone ningun endpoint que abra o cierre
posiciones, ni que cambie configuracion. Aunque alguien llegue a el, no puede
mover dinero. Esa decision es a proposito y no deberia relajarse.

Pensado para mirarse desde el movil.
"""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from learn import Aprendizaje
from modelo import Motor, ahora_ms

PAGINA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Memebot</title>
<!-- Permite instalarlo en la pantalla de inicio como si fuera una app.
     No es un APK: es la propia web, que el sistema abre a pantalla completa. -->
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/svg+xml" href="/icono.svg">
<link rel="apple-touch-icon" href="/icono.svg">
<meta name="theme-color" content="#0e1116">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Memebot">
<style>
  :root {
    --bg:#0e1116; --panel:#161b22; --linea:#262d38; --txt:#e6edf3;
    --suave:#8b949e; --verde:#3fb950; --rojo:#f85149; --ambar:#d29922;
    --acento:#58a6ff;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--txt);
         padding:max(16px, env(safe-area-inset-top)) 16px
                 max(16px, env(safe-area-inset-bottom));
         font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  h1 { font-size:18px; margin:0 0 4px; }
  h2 { font-size:14px; margin:0 0 12px; color:var(--suave);
       text-transform:uppercase; letter-spacing:.06em; }
  .sub { color:var(--suave); font-size:12px; margin-bottom:20px; }
  .panel { background:var(--panel); border:1px solid var(--linea);
           border-radius:10px; padding:16px; margin-bottom:16px; }
  .rejilla { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); }
  .dato { background:var(--bg); border:1px solid var(--linea); border-radius:8px; padding:12px; }
  .dato .et { color:var(--suave); font-size:11px; text-transform:uppercase; letter-spacing:.05em; }
  .dato .val { font-size:20px; font-weight:600; margin-top:4px; font-variant-numeric:tabular-nums; }
  .verde { color:var(--verde); } .rojo { color:var(--rojo); } .ambar { color:var(--ambar); }
  .suave { color:var(--suave); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { text-align:left; color:var(--suave); font-weight:500; font-size:11px;
       text-transform:uppercase; letter-spacing:.05em; padding:6px 8px;
       border-bottom:1px solid var(--linea); }
  td { padding:8px; border-bottom:1px solid var(--linea); font-variant-numeric:tabular-nums; }
  tr:last-child td { border-bottom:none; }
  .leccion { border-left:3px solid var(--acento); padding:12px 14px;
             background:var(--bg); border-radius:0 8px 8px 0; }
  .leccion.bueno { border-left-color:var(--verde); }
  .leccion.malo { border-left-color:var(--rojo); }
  .leccion.neutro { border-left-color:var(--ambar); }
  .leccion .tit { font-weight:600; margin-bottom:6px; }
  .leccion .txt { color:var(--suave); font-size:13px; }
  .concl { padding:10px 12px; border-radius:8px; background:var(--bg);
           border:1px solid var(--linea); margin-bottom:8px; font-size:13px; }
  .concl .nivel { font-size:10px; text-transform:uppercase; letter-spacing:.06em;
                  color:var(--suave); display:block; margin-bottom:4px; }
  .aviso { background:#1c1608; border-color:#3d2f0a; }
  .vacio { color:var(--suave); font-style:italic; padding:8px 0; }
  .pastilla { display:inline-block; padding:2px 8px; border-radius:20px;
              font-size:11px; background:var(--linea); }
  .scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; }
  footer { color:var(--suave); font-size:11px; text-align:center; padding:20px 0; }
</style>
</head>
<body>
  <h1>Memebot</h1>
  <div class="sub" id="cabecera">cargando...</div>
  <div id="app"></div>
  <footer>Panel de solo lectura &middot; se actualiza cada 10 s</footer>

<script>
const eur = (x, d=4) => Number(x).toFixed(d);
const cls = x => Number(x) > 0 ? 'verde' : (Number(x) < 0 ? 'rojo' : 'suave');
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const hora = ms => new Date(ms).toLocaleString('es-ES',
  {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});

function motorPanel(m) {
  return `<div class="panel">
    <h2>Motor ${esc(m.nombre)} ${m.parado ? '<span class="pastilla rojo">DETENIDO</span>' : ''}</h2>
    <div class="rejilla">
      <div class="dato"><div class="et">Equity</div>
        <div class="val">${eur(m.equity,2)}</div></div>
      <div class="dato"><div class="et">Efectivo</div>
        <div class="val">${eur(m.saldo,2)}</div></div>
      <div class="dato"><div class="et">Resultado</div>
        <div class="val ${cls(m.pnl)}">${Number(m.pnl)>=0?'+':''}${eur(m.pnl,2)}</div></div>
      <div class="dato"><div class="et">Posiciones</div>
        <div class="val">${m.posiciones}</div></div>
    </div>
  </div>`;
}

function tabla(cabeceras, filas, vacio) {
  if (!filas.length) return `<div class="vacio">${vacio}</div>`;
  return `<div class="scroll"><table><thead><tr>${
    cabeceras.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${
    filas.join('')}</tbody></table></div>`;
}

async function refrescar() {
  let d;
  try { d = await (await fetch('/api/estado')).json(); }
  catch (e) { document.getElementById('cabecera').textContent = 'sin conexion con el bot'; return; }

  document.getElementById('cabecera').innerHTML =
    `${d.feed_real ? 'Precios reales de Binance' : 'Feed sintetico (pruebas)'} &middot; ` +
    `dinero virtual &middot; ${d.ciclos} ciclos &middot; activo desde ${hora(d.arrancado_ms)}`;

  let html = d.motores.map(motorPanel).join('');

  const l = d.ultima_leccion;
  html += `<div class="panel"><h2>Lo ultimo aprendido</h2>` + (l
    ? `<div class="leccion ${esc(l.tipo)}">
         <div class="tit">${esc(l.simbolo)} &middot; ${esc(l.titulo)}
           <span class="${cls(l.pnl)}">${esc(l.pnl_pct)}%</span></div>
         <div class="txt">${esc(l.texto)}</div>
         <div class="txt" style="margin-top:6px;font-size:11px">
           regla ${esc(l.regla)} &middot; ${hora(l.ts_ms)}</div>
       </div>`
    : `<div class="vacio">Todavia no se ha cerrado ninguna operacion.</div>`) + `</div>`;

  html += `<div class="panel"><h2>Que sabemos hasta ahora</h2>` +
    (d.aprendizaje.conclusiones.length
      ? d.aprendizaje.conclusiones.map(c =>
          `<div class="concl ${c.nivel==='aviso'?'aviso':''}">
             <span class="nivel">${esc(c.nivel)}</span>${esc(c.texto)}</div>`).join('')
      : `<div class="vacio">Sin datos suficientes.</div>`) + `</div>`;

  html += `<div class="panel"><h2>Rendimiento por regla</h2>` + tabla(
    ['Regla','Ops','Acierto','Resultado','Media/op'],
    Object.entries(d.aprendizaje.por_regla).map(([k,v]) =>
      `<tr><td>${esc(k)}</td><td>${v.n}</td>
       <td>${v.tasa.toFixed(0)}% <span class="suave">±${v.margen.toFixed(0)}</span></td>
       <td class="${cls(v.pnl)}">${eur(v.pnl,4)}</td>
       <td class="${cls(v.pnl_medio)}">${eur(v.pnl_medio,4)}</td></tr>`),
    'Sin operaciones cerradas.') + `</div>`;

  html += `<div class="panel"><h2>Posiciones abiertas</h2>` + tabla(
    ['Par','Motor','Entrada','Actual','PnL','Regla'],
    d.posiciones.map(p =>
      `<tr><td>${esc(p.simbolo)}</td><td class="suave">${esc(p.motor)}</td>
       <td>${p.precio_entrada}</td><td>${p.precio_actual}</td>
       <td class="${cls(p.pnl_pct)}">${Number(p.pnl_pct)>=0?'+':''}${Number(p.pnl_pct).toFixed(2)}%</td>
       <td class="suave">${esc(p.regla)}</td></tr>`),
    'Ninguna posicion abierta ahora mismo.') + `</div>`;

  html += `<div class="panel"><h2>Operaciones recientes</h2>` + tabla(
    ['Cierre','Par','Regla','Salida','Resultado'],
    d.operaciones.map(o =>
      `<tr><td class="suave">${hora(o.salida_ms)}</td><td>${esc(o.simbolo)}</td>
       <td class="suave">${esc(o.regla)}</td><td class="suave">${esc(o.motivo_salida)}</td>
       <td class="${cls(o.pnl)}">${Number(o.pnl_pct)>=0?'+':''}${Number(o.pnl_pct).toFixed(2)}%
         <span class="suave">(${eur(o.pnl,4)})</span></td></tr>`),
    'Sin operaciones todavia.') + `</div>`;

  html += `<div class="panel"><h2>Journal de decisiones</h2>` + tabla(
    ['Hora','Par','Accion','Motivo'],
    d.decisiones.map(x =>
      `<tr><td class="suave">${hora(x.ts_ms)}</td><td>${esc(x.simbolo)}</td>
       <td>${esc(x.accion)}</td><td class="suave">${esc(x.motivo)}</td></tr>`),
    'Sin decisiones registradas.') + `</div>`;

  html += `<div class="panel"><h2>Incidentes</h2>` + tabla(
    ['Hora','Tipo','Detalle'],
    d.incidentes.map(x =>
      `<tr><td class="suave">${hora(x.ts_ms)}</td><td>${esc(x.tipo)}</td>
       <td class="suave">${esc(x.detalle).slice(0,160)}</td></tr>`),
    'Ningun incidente. Bien.') + `</div>`;

  document.getElementById('app').innerHTML = html;
}
refrescar();
setInterval(refrescar, 10000);
</script>
</body>
</html>"""


# Icono propio, dibujado a mano: dos velas japonesas sobre fondo oscuro.
ICONO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">
  <rect width="192" height="192" rx="42" fill="#0e1116"/>
  <g stroke-linecap="round">
    <line x1="70" y1="38" x2="70" y2="150" stroke="#3fb950" stroke-width="7"/>
    <rect x="55" y="62" width="30" height="66" rx="5" fill="#3fb950"/>
    <line x1="124" y1="52" x2="124" y2="160" stroke="#f85149" stroke-width="7"/>
    <rect x="109" y="84" width="30" height="52" rx="5" fill="#f85149"/>
  </g>
</svg>"""

MANIFEST = {
    "name": "Memebot",
    "short_name": "Memebot",
    "description": "Panel del bot de trading en papel",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0e1116",
    "theme_color": "#0e1116",
    "orientation": "portrait",
    "icons": [
        {"src": "/icono.svg", "sizes": "any", "type": "image/svg+xml",
         "purpose": "any maskable"}
    ],
}


def _dec(x) -> str:
    return str(x)


class Handler(BaseHTTPRequestHandler):
    bot = None          # inyectado por servir()
    store = None

    def log_message(self, *_args):
        pass            # sin ruido en consola

    def _responder(self, codigo: int, cuerpo: bytes, tipo: str) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):  # noqa: N802 - lo impone BaseHTTPRequestHandler
        if self.path == "/":
            self._responder(200, PAGINA.encode(), "text/html; charset=utf-8")
        elif self.path == "/manifest.json":
            self._responder(200, json.dumps(MANIFEST).encode(),
                            "application/manifest+json; charset=utf-8")
        elif self.path == "/icono.svg":
            self._responder(200, ICONO.encode(), "image/svg+xml; charset=utf-8")
        elif self.path == "/api/estado":
            datos = json.dumps(self._estado(), default=str).encode()
            self._responder(200, datos, "application/json; charset=utf-8")
        else:
            self._responder(404, b"no encontrado", "text/plain; charset=utf-8")

    # Sin do_POST: el panel no puede ordenar nada. A proposito.

    def _estado(self) -> dict:
        bot, store = Handler.bot, Handler.store
        try:
            precios = bot.feed.precios(bot.simbolos)
        except Exception:  # noqa: BLE001
            precios = {}

        motores = []
        for cfg in bot.motores:
            eq = bot.equity(cfg.motor, precios)
            inicial = bot.riesgo.limites[cfg.motor].capital_inicial
            motores.append({
                "nombre": cfg.motor.value,
                "equity": _dec(eq.quantize(Decimal("0.01"))),
                "saldo": _dec(bot.broker.saldo(cfg.motor).quantize(Decimal("0.01"))),
                "pnl": _dec((eq - inicial).quantize(Decimal("0.01"))),
                "posiciones": sum(1 for p in bot.posiciones if p.motor is cfg.motor),
                "parado": bot.riesgo.esta_parado(cfg.motor),
            })

        posiciones = []
        for p in bot.posiciones:
            actual = precios.get(p.simbolo, p.precio_entrada)
            posiciones.append({
                "simbolo": p.simbolo, "motor": p.motor.value,
                "precio_entrada": _dec(p.precio_entrada),
                "precio_actual": _dec(actual),
                "pnl_pct": _dec(p.pnl_pct(actual).quantize(Decimal("0.01"))),
                "regla": p.regla,
            })

        ops = store.operaciones(limite=25)
        informe = Aprendizaje(store).informe()

        return {
            "ahora_ms": ahora_ms(),
            "arrancado_ms": bot.arrancado_ms,
            "ciclos": bot.ciclos,
            "feed_real": bot.feed.es_real,
            "broker_real": bot.broker.es_real,
            "motores": motores,
            "posiciones": posiciones,
            "ultima_leccion": store.get_estado("ultima_leccion"),
            "aprendizaje": informe,
            "operaciones": [
                {"salida_ms": o.salida_ms, "simbolo": o.simbolo, "regla": o.regla,
                 "motivo_salida": o.motivo_salida.value, "pnl": _dec(o.pnl),
                 "pnl_pct": _dec(o.pnl_pct)}
                for o in ops
            ],
            "decisiones": store.decisiones(limite=40, solo_acciones=True),
            "incidentes": store.incidentes(limite=20),
        }


def servir(bot, store, puerto: int = 8080, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Arranca el dashboard en un hilo aparte.

    Por defecto escucha SOLO en 127.0.0.1. Para verlo desde otro dispositivo,
    usa una VPN (Tailscale) en lugar de abrirlo a internet: es un panel de un
    bot de trading, no conviene dejarlo expuesto.
    """
    Handler.bot = bot
    Handler.store = store
    servidor = ThreadingHTTPServer((host, puerto), Handler)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    return servidor
