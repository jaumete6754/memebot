"""Journal persistente en SQLite.

Todo pasa por aqui: decisiones, operaciones, incidentes y posiciones abiertas.
Es un unico fichero, facil de copiar y respaldar.

Las posiciones abiertas se persisten a proposito: el proceso se va a morir
(Android mata procesos en segundo plano), y al reiniciar tiene que recuperar
exactamente donde estaba. Un bot que olvida sus posiciones al reiniciar es un
bot que deja stops sin vigilar.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from modelo import (
    Decision,
    Incidente,
    Motor,
    MotivoSalida,
    Operacion,
    Posicion,
    ahora_ms,
)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS decisiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    motor TEXT NOT NULL,
    simbolo TEXT NOT NULL,
    accion TEXT NOT NULL,
    regla TEXT NOT NULL,
    motivo TEXT NOT NULL,
    precio TEXT NOT NULL,
    contexto TEXT NOT NULL,
    version_config TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dec_ts ON decisiones(ts_ms DESC);

CREATE TABLE IF NOT EXISTS operaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motor TEXT NOT NULL,
    simbolo TEXT NOT NULL,
    cantidad TEXT NOT NULL,
    precio_entrada TEXT NOT NULL,
    precio_salida TEXT NOT NULL,
    entrada_ms INTEGER NOT NULL,
    salida_ms INTEGER NOT NULL,
    motivo_salida TEXT NOT NULL,
    regla TEXT NOT NULL,
    comisiones TEXT NOT NULL,
    pnl TEXT NOT NULL,
    pnl_pct TEXT NOT NULL,
    tp_esperado_pct TEXT NOT NULL,
    sl_esperado_pct TEXT NOT NULL,
    regimen TEXT NOT NULL DEFAULT 'desconocido'
);
CREATE INDEX IF NOT EXISTS idx_op_salida ON operaciones(salida_ms DESC);

CREATE TABLE IF NOT EXISTS incidentes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    detalle TEXT NOT NULL,
    severidad TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inc_ts ON incidentes(ts_ms DESC);

CREATE TABLE IF NOT EXISTS posiciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motor TEXT NOT NULL,
    simbolo TEXT NOT NULL,
    cantidad TEXT NOT NULL,
    precio_entrada TEXT NOT NULL,
    entrada_ms INTEGER NOT NULL,
    stop_loss TEXT NOT NULL,
    take_profit TEXT NOT NULL,
    stop_inicial TEXT NOT NULL DEFAULT '0',
    trailing_pct TEXT,
    max_precio_visto TEXT NOT NULL,
    limite_tiempo_ms INTEGER,
    regla TEXT NOT NULL,
    comision_entrada TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS estado (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS velas (
    simbolo TEXT NOT NULL,
    apertura_ms INTEGER NOT NULL,
    apertura TEXT NOT NULL,
    maximo TEXT NOT NULL,
    minimo TEXT NOT NULL,
    cierre TEXT NOT NULL,
    volumen TEXT NOT NULL,
    PRIMARY KEY (simbolo, apertura_ms)
);
"""


class Store:
    """Acceso al journal. Seguro entre hilos (el dashboard lee mientras el bot escribe)."""

    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(self.ruta), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        # WAL permite leer mientras se escribe, que es justo lo que hace el dashboard.
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript(ESQUEMA)
        self._con.commit()

    def cerrar(self) -> None:
        with self._lock:
            self._con.close()

    # ---------------------------------------------------------------- estado

    def get_estado(self, clave: str, defecto: Any = None) -> Any:
        with self._lock:
            fila = self._con.execute(
                "SELECT valor FROM estado WHERE clave = ?", (clave,)
            ).fetchone()
        return json.loads(fila["valor"]) if fila else defecto

    def set_estado(self, clave: str, valor: Any) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO estado (clave, valor) VALUES (?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (clave, json.dumps(valor)),
            )
            self._con.commit()

    # ------------------------------------------------------------ decisiones

    def guardar_decision(self, d: Decision) -> int:
        with self._lock:
            cur = self._con.execute(
                "INSERT INTO decisiones "
                "(ts_ms, motor, simbolo, accion, regla, motivo, precio, contexto, version_config) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    d.ts_ms, d.motor.value, d.simbolo, d.accion, d.regla, d.motivo,
                    str(d.precio), json.dumps(d.contexto, default=str), d.version_config,
                ),
            )
            self._con.commit()
            return int(cur.lastrowid)

    def decisiones(self, limite: int = 200, solo_acciones: bool = False) -> list[dict]:
        sql = "SELECT * FROM decisiones"
        if solo_acciones:
            sql += " WHERE accion != 'esperar'"
        sql += " ORDER BY ts_ms DESC LIMIT ?"
        with self._lock:
            filas = self._con.execute(sql, (limite,)).fetchall()
        return [dict(f) for f in filas]

    # ----------------------------------------------------------- operaciones

    def guardar_operacion(self, op: Operacion) -> int:
        with self._lock:
            cur = self._con.execute(
                "INSERT INTO operaciones "
                "(motor, simbolo, cantidad, precio_entrada, precio_salida, entrada_ms, "
                " salida_ms, motivo_salida, regla, comisiones, pnl, pnl_pct, "
                " tp_esperado_pct, sl_esperado_pct, regimen) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    op.motor.value, op.simbolo, str(op.cantidad), str(op.precio_entrada),
                    str(op.precio_salida), op.entrada_ms, op.salida_ms,
                    op.motivo_salida.value, op.regla, str(op.comisiones), str(op.pnl),
                    str(op.pnl_pct), str(op.tp_esperado_pct), str(op.sl_esperado_pct),
                    op.regimen,
                ),
            )
            self._con.commit()
            return int(cur.lastrowid)

    def operaciones(self, limite: int = 500, motor: Optional[Motor] = None) -> list[Operacion]:
        sql = "SELECT * FROM operaciones"
        params: list = []
        if motor:
            sql += " WHERE motor = ?"
            params.append(motor.value)
        sql += " ORDER BY salida_ms DESC LIMIT ?"
        params.append(limite)
        with self._lock:
            filas = self._con.execute(sql, params).fetchall()
        return [self._fila_a_operacion(f) for f in filas]

    @staticmethod
    def _fila_a_operacion(f: sqlite3.Row) -> Operacion:
        return Operacion(
            id=f["id"],
            motor=Motor(f["motor"]),
            simbolo=f["simbolo"],
            cantidad=Decimal(f["cantidad"]),
            precio_entrada=Decimal(f["precio_entrada"]),
            precio_salida=Decimal(f["precio_salida"]),
            entrada_ms=f["entrada_ms"],
            salida_ms=f["salida_ms"],
            motivo_salida=MotivoSalida(f["motivo_salida"]),
            regla=f["regla"],
            comisiones=Decimal(f["comisiones"]),
            pnl=Decimal(f["pnl"]),
            pnl_pct=Decimal(f["pnl_pct"]),
            tp_esperado_pct=Decimal(f["tp_esperado_pct"]),
            sl_esperado_pct=Decimal(f["sl_esperado_pct"]),
            regimen=f["regimen"] if "regimen" in f.keys() else "desconocido",
        )

    # ------------------------------------------------------------ posiciones

    def guardar_posicion(self, p: Posicion) -> int:
        with self._lock:
            cur = self._con.execute(
                "INSERT INTO posiciones "
                "(motor, simbolo, cantidad, precio_entrada, entrada_ms, stop_loss, "
                " take_profit, stop_inicial, trailing_pct, max_precio_visto, "
                " limite_tiempo_ms, regla, comision_entrada) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    p.motor.value, p.simbolo, str(p.cantidad), str(p.precio_entrada),
                    p.entrada_ms, str(p.stop_loss), str(p.take_profit),
                    str(p.stop_inicial),
                    str(p.trailing_pct) if p.trailing_pct is not None else None,
                    str(p.max_precio_visto), p.limite_tiempo_ms, p.regla,
                    str(p.comision_entrada),
                ),
            )
            self._con.commit()
            return int(cur.lastrowid)

    def actualizar_posicion(self, p: Posicion) -> None:
        with self._lock:
            self._con.execute(
                "UPDATE posiciones SET stop_loss=?, max_precio_visto=? WHERE id=?",
                (str(p.stop_loss), str(p.max_precio_visto), p.id),
            )
            self._con.commit()

    def borrar_posicion(self, pos_id: int) -> None:
        with self._lock:
            self._con.execute("DELETE FROM posiciones WHERE id = ?", (pos_id,))
            self._con.commit()

    def posiciones_abiertas(self) -> list[Posicion]:
        with self._lock:
            filas = self._con.execute("SELECT * FROM posiciones").fetchall()
        return [
            Posicion(
                id=f["id"],
                motor=Motor(f["motor"]),
                simbolo=f["simbolo"],
                cantidad=Decimal(f["cantidad"]),
                precio_entrada=Decimal(f["precio_entrada"]),
                entrada_ms=f["entrada_ms"],
                stop_loss=Decimal(f["stop_loss"]),
                take_profit=Decimal(f["take_profit"]),
                stop_inicial=Decimal(f["stop_inicial"]),
                trailing_pct=Decimal(f["trailing_pct"]) if f["trailing_pct"] else None,
                max_precio_visto=Decimal(f["max_precio_visto"]),
                limite_tiempo_ms=f["limite_tiempo_ms"],
                regla=f["regla"],
                comision_entrada=Decimal(f["comision_entrada"]),
            )
            for f in filas
        ]

    # ------------------------------------------------------------ incidentes

    def guardar_incidente(self, inc: Incidente) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO incidentes (ts_ms, tipo, detalle, severidad) VALUES (?,?,?,?)",
                (inc.ts_ms, inc.tipo, inc.detalle, inc.severidad),
            )
            self._con.commit()

    def incidente(self, tipo: str, detalle: str, severidad: str = "aviso") -> None:
        """Atajo para registrar un incidente sin construir el objeto."""
        self.guardar_incidente(Incidente(ahora_ms(), tipo, detalle, severidad))

    def incidentes(self, limite: int = 100) -> list[dict]:
        with self._lock:
            filas = self._con.execute(
                "SELECT * FROM incidentes ORDER BY ts_ms DESC LIMIT ?", (limite,)
            ).fetchall()
        return [dict(f) for f in filas]

    # ----------------------------------------------------------------- velas

    def guardar_velas(self, velas) -> int:
        """Guarda velas ignorando duplicados. Devuelve cuantas eran nuevas."""
        nuevas = 0
        with self._lock:
            for v in velas:
                cur = self._con.execute(
                    "INSERT OR IGNORE INTO velas "
                    "(simbolo, apertura_ms, apertura, maximo, minimo, cierre, volumen) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        v.simbolo, v.apertura_ms, str(v.apertura), str(v.maximo),
                        str(v.minimo), str(v.cierre), str(v.volumen),
                    ),
                )
                nuevas += cur.rowcount
            self._con.commit()
        return nuevas

    def contar_velas(self) -> int:
        with self._lock:
            return int(self._con.execute("SELECT COUNT(*) c FROM velas").fetchone()["c"])
