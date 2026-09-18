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
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/svg+xml" href="/icono.svg">
<link rel="apple-touch-icon" href="/icono.svg">
<meta name="theme-color" content="#0e1217">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Memebot">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
  :root {
    --bg:#f4f6f8; --sup:#ffffff; --sup2:#eef1f4; --ink:#161b21; --mut:#5e6b78;
    --line:#dfe4e9; --acc:#2f6bc4; --pos:#17794c; --neg:#b93a2e; --warn:#96660f;
    --posbg:#e6f4ec; --negbg:#fcebe8; --warnbg:#fbf2e0; --r:10px;
    --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg:#0e1217; --sup:#161b22; --sup2:#1b222a; --ink:#e6edf3; --mut:#8b97a4;
      --line:#252d36; --acc:#6ea8fe; --pos:#48c98a; --neg:#f2705f; --warn:#d5a13d;
      --posbg:#11291e; --negbg:#2a1614; --warnbg:#2a2211;
    }
  }
  :root[data-theme="dark"] {
    --bg:#0e1217; --sup:#161b22; --sup2:#1b222a; --ink:#e6edf3; --mut:#8b97a4;
    --line:#252d36; --acc:#6ea8fe; --pos:#48c98a; --neg:#f2705f; --warn:#d5a13d;
    --posbg:#11291e; --negbg:#2a1614; --warnbg:#2a2211;
  }
  * { box-sizing:border-box; }
  html, body { margin:0; }
  body { background:var(--bg); color:var(--ink); font-family:var(--sans); font-size:14px;
         line-height:1.5;
         padding:max(16px, env(safe-area-inset-top)) 16px max(24px, env(safe-area-inset-bottom)); }
  .wrap { max-width:760px; margin:0 auto; }
  header { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:6px; }
  h1 { font-size:20px; font-weight:600; margin:0; letter-spacing:-0.01em; }
  .estado-linea { color:var(--mut); font-size:12.5px; font-family:var(--mono); margin-bottom:20px; }
  .punto { display:inline-block; width:7px; height:7px; border-radius:50%;
           background:var(--mut); margin-right:5px; vertical-align:middle; }
  .punto.vivo { background:var(--pos); } .punto.malo { background:var(--neg); }
  section { margin-bottom:22px; }
  h2 { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.09em;
       color:var(--mut); margin:0 0 10px; }
  .motores { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); }
  .motor { background:var(--sup); border:1px solid var(--line); border-radius:var(--r); padding:14px 16px; }
  .motor-cab { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:12px; }
  .motor-nom { font-weight:600; font-size:13px; letter-spacing:.02em; text-transform:uppercase; }
  .cifras { display:grid; grid-template-columns:1fr 1fr; gap:10px 14px; }
  .cifra .et { font-size:10.5px; text-transform:uppercase; letter-spacing:.06em; color:var(--mut); }
  .cifra .v { font-family:var(--mono); font-size:19px; font-weight:500; font-variant-numeric:tabular-nums; }
  .cifra.small .v { font-size:15px; }
  .pill { font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:.06em;
          padding:3px 8px; border-radius:20px; background:var(--sup2); color:var(--mut); white-space:nowrap; }
  .pill.stop { background:var(--negbg); color:var(--neg); }
  .leccion { background:var(--sup); border:1px solid var(--line); border-radius:var(--r);
             border-left:3px solid var(--mut); padding:14px 16px; }
  .leccion.bueno { border-left-color:var(--pos); }
  .leccion.malo { border-left-color:var(--neg); }
  .leccion.neutro { border-left-color:var(--warn); }
  .leccion-cab { display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; margin-bottom:6px; }
  .leccion-par { font-family:var(--mono); font-weight:600; }
  .leccion-tit { font-weight:600; }
  .leccion p { margin:0; color:var(--mut); }
  .leccion .meta { margin-top:8px; font-family:var(--mono); font-size:11px; color:var(--mut); }
  .nota { border-radius:var(--r); padding:11px 14px; font-size:13px;
          border:1px solid var(--line); background:var(--sup); }
  .nota + .nota { margin-top:8px; }
  .nota .nv { display:block; font-size:10px; text-transform:uppercase; letter-spacing:.07em;
              color:var(--mut); margin-bottom:3px; font-weight:600; }
  .nota.aviso { background:var(--warnbg); border-color:transparent; }
  .nota.insuficiente { background:var(--sup2); border-color:transparent; }
  .tabla-caja { overflow-x:auto; background:var(--sup); border:1px solid var(--line); border-radius:var(--r); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { text-align:left; font-size:10px; text-transform:uppercase; letter-spacing:.06em;
       color:var(--mut); font-weight:600; padding:9px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }
  td { padding:9px 12px; border-bottom:1px solid var(--line);
       font-variant-numeric:tabular-nums; white-space:nowrap; }
  tr:last-child td { border-bottom:none; }
  td.num, th.num { text-align:right; font-family:var(--mono); }
  td.par { font-family:var(--mono); font-weight:500; }
  td.leve { color:var(--mut); }
  .pos { color:var(--pos); } .neg { color:var(--neg); } .mut { color:var(--mut); }
  .vacio { color:var(--mut); font-style:italic; padding:14px 16px; background:var(--sup);
           border:1px solid var(--line); border-radius:var(--r); }
  footer { color:var(--mut); font-size:11.5px; border-top:1px solid var(--line);
           padding-top:14px; margin-top:30px; }
  footer p { margin:0 0 6px; }
  @media (prefers-reduced-motion: reduce) { * { animation:none !important; transition:none !important; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Memebot</h1>
    <span class="pill" id="pillModo">papel</span>
  </header>
  <div class="estado-linea" id="estadoLinea"><span class="punto"></span>conectando&hellip;</div>

  <section><h2>Motores</h2><div class="motores" id="motores"></div></section>
  <section><h2>Lo último aprendido</h2><div id="leccion"></div></section>
  <section><h2>Qué sabemos hasta ahora</h2><div id="conclusiones"></div></section>
  <section><h2>Rendimiento por regla</h2><div id="porRegla"></div></section>
  <section><h2>Posiciones abiertas</h2><div id="posiciones"></div></section>
  <section><h2>Operaciones cerradas</h2><div id="operaciones"></div></section>
  <section><h2>Journal de decisiones</h2><div id="journal"></div></section>
  <section><h2>Incidentes</h2><div id="incidentes"></div></section>

  <footer>
    <p><strong>Todo el dinero es virtual.</strong> Los precios son reales, de los endpoints públicos
       de Binance. No existe ninguna clave de API en el proyecto.</p>
    <p>Panel de solo lectura: no puede abrir ni cerrar posiciones. Se actualiza cada 10 s.</p>
  </footer>
</div>

<script>
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num = (x, d=2) => Number(x).toFixed(d);
const sgn = (x, d=2) => (Number(x) >= 0 ? '+' : '') + Number(x).toFixed(d);
const cls = x => Number(x) > 0 ? 'pos' : (Number(x) < 0 ? 'neg' : 'mut');
const hora = ms => new Date(ms).toLocaleString('es-ES',
  {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
const precioTxt = p => { const n = Number(p);
  return n >= 1 ? n.toFixed(4) : n.toPrecision(5); };

function tabla(cabs, filas, vacio) {
  if (!filas.length) return '<div class="vacio">' + vacio + '</div>';
  return '<div class="tabla-caja"><table><thead><tr>' +
    cabs.map(c => '<th' + (c[1] ? ' class="num"' : '') + '>' + c[0] + '</th>').join('') +
    '</tr></thead><tbody>' + filas.join('') + '</tbody></table></div>';
}

async function refrescar() {
  let d;
  try { d = await (await fetch('/api/estado')).json(); }
  catch (e) {
    document.getElementById('estadoLinea').innerHTML =
      '<span class="punto malo"></span>sin conexión con el bot';
    return;
  }

  document.getElementById('pillModo').textContent =
    d.broker_real ? 'dinero real' : 'papel';

  const partes = [
    d.feed_real ? 'precios reales de Binance' : 'feed sintético (pruebas)',
    d.ciclos + (d.ciclos === 1 ? ' ciclo' : ' ciclos'),
    'activo desde ' + hora(d.arrancado_ms),
  ];
  document.getElementById('estadoLinea').innerHTML =
    '<span class="punto ' + (d.ciclos > 0 ? 'vivo' : '') + '"></span>' +
    partes.map(esc).join(' · ');

  document.getElementById('motores').innerHTML = d.motores.map(m =>
    '<div class="motor"><div class="motor-cab">' +
      '<span class="motor-nom">' + esc(m.nombre) + '</span>' +
      (m.parado ? '<span class="pill stop">detenido</span>'
                : '<span class="pill">' + m.posiciones + ' posiciones</span>') +
    '</div><div class="cifras">' +
      '<div class="cifra"><div class="et">Equity</div><div class="v">' + num(m.equity) + '</div></div>' +
      '<div class="cifra"><div class="et">Resultado</div><div class="v ' + cls(m.pnl) + '">' +
        sgn(m.pnl) + '</div></div>' +
      '<div class="cifra small"><div class="et">Efectivo</div><div class="v">' + num(m.saldo) + '</div></div>' +
      '<div class="cifra small"><div class="et">En mercado</div><div class="v">' +
        num(Number(m.equity) - Number(m.saldo)) + '</div></div>' +
    '</div></div>').join('');

  const l = d.ultima_leccion;
  document.getElementById('leccion').innerHTML = l
    ? '<div class="leccion ' + esc(l.tipo) + '"><div class="leccion-cab">' +
        '<span class="leccion-par">' + esc(l.simbolo) + '</span>' +
        '<span class="leccion-tit">' + esc(l.titulo) + '</span>' +
        '<span class="' + (String(l.pnl_pct).startsWith('-') ? 'neg' : 'pos') + '">' +
          esc(l.pnl_pct) + '%</span></div>' +
        '<p>' + esc(l.texto) + '</p>' +
        '<div class="meta">regla ' + esc(l.regla) + ' · ' + hora(l.ts_ms) + '</div></div>'
    : '<div class="vacio">Todavía no se ha cerrado ninguna operación. En cuanto se cierre la ' +
      'primera, aquí aparecerá qué esperaba el bot, qué pasó y qué se deduce de la diferencia.</div>';

  document.getElementById('conclusiones').innerHTML =
    (d.aprendizaje.conclusiones || []).map(c =>
      '<div class="nota ' + (c.nivel === 'aviso' ? 'aviso' :
        (c.nivel === 'insuficiente' ? 'insuficiente' : '')) + '">' +
      '<span class="nv">' + esc(c.nivel) + '</span>' + esc(c.texto) + '</div>').join('')
    || '<div class="vacio">Sin datos todavía.</div>';

  document.getElementById('porRegla').innerHTML = tabla(
    [['Regla'],['Ops',1],['Acierto',1],['Resultado',1],['Media/op',1]],
    Object.entries(d.aprendizaje.por_regla || {}).map(([k,v]) =>
      '<tr><td>' + esc(k) + '</td><td class="num">' + v.n + '</td>' +
      '<td class="num">' + v.tasa.toFixed(0) + '% <span class="mut">±' +
        v.margen.toFixed(0) + '</span></td>' +
      '<td class="num ' + cls(v.pnl) + '">' + num(v.pnl, 4) + '</td>' +
      '<td class="num ' + cls(v.pnl_medio) + '">' + num(v.pnl_medio, 4) + '</td></tr>'),
    'Sin operaciones cerradas todavía.');

  document.getElementById('posiciones').innerHTML = tabla(
    [['Par'],['Motor'],['Entrada',1],['Actual',1],['PnL',1],['Regla']],
    d.posiciones.map(p =>
      '<tr><td class="par">' + esc(p.simbolo) + '</td>' +
      '<td class="leve">' + esc(p.motor) + '</td>' +
      '<td class="num leve">' + precioTxt(p.precio_entrada) + '</td>' +
      '<td class="num">' + precioTxt(p.precio_actual) + '</td>' +
      '<td class="num ' + cls(p.pnl_pct) + '">' + sgn(p.pnl_pct) + '%</td>' +
      '<td class="leve">' + esc(p.regla) + '</td></tr>'),
    'Ninguna posición abierta ahora mismo.');

  document.getElementById('operaciones').innerHTML = tabla(
    [['Cierre'],['Par'],['Regla'],['Salida'],['Resultado',1]],
    d.operaciones.map(o =>
      '<tr><td class="leve">' + hora(o.salida_ms) + '</td>' +
      '<td class="par">' + esc(o.simbolo) + '</td>' +
      '<td class="leve">' + esc(o.regla) + '</td>' +
      '<td class="leve">' + esc(o.motivo_salida) + '</td>' +
      '<td class="num ' + cls(o.pnl) + '">' + sgn(o.pnl_pct) + '% <span class="mut">(' +
        num(o.pnl, 4) + ')</span></td></tr>'),
    'Sin operaciones cerradas todavía.');

  document.getElementById('journal').innerHTML = tabla(
    [['Hora'],['Par'],['Acción'],['Motivo']],
    d.decisiones.map(x =>
      '<tr><td class="leve">' + hora(x.ts_ms) + '</td>' +
      '<td class="par">' + esc(x.simbolo) + '</td>' +
      '<td>' + esc(x.accion) + '</td>' +
      '<td class="leve">' + esc(x.motivo) + '</td></tr>'),
    'Sin decisiones registradas todavía.');

  document.getElementById('incidentes').innerHTML = tabla(
    [['Hora'],['Tipo'],['Detalle']],
    d.incidentes.map(x =>
      '<tr><td class="leve">' + hora(x.ts_ms) + '</td>' +
      '<td>' + esc(x.tipo) + '</td>' +
      '<td class="leve">' + esc(String(x.detalle).slice(0,160)) + '</td></tr>'),
    'Ningún incidente. Bien.');
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
        # El navegador cierra la conexion en cuanto cambias de pestana o
        # refrescas, y el socket se rompe a mitad de la respuesta. Es normal y
        # no es un fallo del bot: se ignora en silencio en vez de volcar una
        # traza cada diez segundos.
        try:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(cuerpo)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def handle_one_request(self):  # noqa: N802
        """Igual que el original, pero sin traza cuando el cliente se va."""
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

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
