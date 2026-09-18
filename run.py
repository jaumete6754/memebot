#!/usr/bin/env python3
"""Arranque del bot.

    python3 run.py                  # usa config.json
    python3 run.py --sintetico      # fuerza feed sintetico (sin conexion)
    python3 run.py --rapido         # ciclos de 5 s, para ver resultados ya

Todo el dinero es virtual. No hay claves de API en ningun sitio del proyecto.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from decimal import Decimal
from pathlib import Path

from broker import BrokerPapel
from dashboard import servir
from engine import Bot, ConfigMotor
from feed import ErrorFeed, FeedBinance, FeedSintetico
from risk import GestorRiesgo, LimitesMotor
from store import Store
from strategies import CruceMedias, Exploracion, RupturaVolumen
from modelo import Motor

RAIZ = Path(__file__).resolve().parent


def cargar_config(ruta: Path) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def validar_simbolos(feed: FeedBinance, simbolos: list[str], store) -> list[str]:
    """Descarta los pares que no existan en Binance.

    Los listados cambian: un par que existia hace meses puede estar retirado.
    Mejor detectarlo al arrancar que fallar en mitad de un ciclo.
    """
    validos = []
    for s in simbolos:
        try:
            feed.precios([s])
            validos.append(s)
        except ErrorFeed:
            store.incidente("simbolo_invalido", f"{s} no disponible, se ignora", "aviso")
            print(f"  aviso: {s} no disponible en Binance, se ignora")
    return validos


def main() -> int:
    ap = argparse.ArgumentParser(description="Memebot - trading en papel")
    ap.add_argument("--config", default=str(RAIZ / "config.json"))
    ap.add_argument("--sintetico", action="store_true",
                    help="fuerza feed sintetico, sin conexion")
    ap.add_argument("--rapido", action="store_true",
                    help="ciclos de 5 s en vez de 60")
    ap.add_argument("--datos", default=str(RAIZ / "datos" / "memebot.db"))
    args = ap.parse_args()

    cfg = cargar_config(Path(args.config))
    store = Store(args.datos)

    # ------------------------------------------------------------ simbolos
    simbolos_por_motor = {
        Motor.NUCLEO: cfg["motores"]["nucleo"]["simbolos"],
        Motor.SATELITE: cfg["motores"]["satelite"]["simbolos"],
    }
    todos = [s for lista in simbolos_por_motor.values() for s in lista]

    # ---------------------------------------------------------------- feed
    usar_sintetico = args.sintetico or cfg.get("modo_feed") == "sintetico"
    if usar_sintetico:
        feed = FeedSintetico(todos)
        print("Feed SINTETICO: los precios son inventados. Solo para probar la fontaneria.")
    else:
        feed = FeedBinance(store=store)
        print("Feed REAL: precios en vivo de Binance (endpoints publicos, sin claves).")
        print("Comprobando simbolos...")
        for motor, lista in simbolos_por_motor.items():
            simbolos_por_motor[motor] = validar_simbolos(feed, lista, store)
        if not any(simbolos_por_motor.values()):
            print("\nNo se pudo contactar con Binance ni validar ningun simbolo.")
            print("Comprueba tu conexion, o arranca con --sintetico para probar sin red.")
            return 1

    # -------------------------------------------------------------- broker
    cap_nucleo = Decimal(cfg["motores"]["nucleo"]["capital"])
    cap_satelite = Decimal(cfg["motores"]["satelite"]["capital"])
    broker = BrokerPapel(
        saldos={Motor.NUCLEO: cap_nucleo, Motor.SATELITE: cap_satelite},
        comision_pct=Decimal(cfg["comision_pct"]),
        slippage_pct=Decimal(cfg["slippage_pct"]),
        store=store,
    )

    # -------------------------------------------------------------- riesgo
    def limites(clave: str, capital: Decimal) -> LimitesMotor:
        m = cfg["motores"][clave]
        return LimitesMotor(
            capital_inicial=capital,
            max_posiciones=int(m["max_posiciones"]),
            importe_por_operacion=Decimal(m["importe_por_operacion"]),
            max_drawdown_pct=Decimal(m["max_drawdown_pct"]),
            max_exposicion_pct=Decimal(m["max_exposicion_pct"]),
        )

    riesgo = GestorRiesgo(
        limites={
            Motor.NUCLEO: limites("nucleo", cap_nucleo),
            Motor.SATELITE: limites("satelite", cap_satelite),
        },
        store=store,
    )

    # --------------------------------------------------------- estrategias
    estrategias_nucleo = [CruceMedias(), RupturaVolumen()]
    estrategias_satelite = [RupturaVolumen(ventana=20)]
    if cfg.get("exploracion", True):
        p = float(cfg.get("prob_exploracion", 0.12))
        estrategias_nucleo.append(Exploracion(prob_entrada=p, semilla=7))
        # El satelite explora mas: es su razon de ser.
        estrategias_satelite.append(Exploracion(prob_entrada=p * 2, semilla=13))

    motores = [
        ConfigMotor(Motor.NUCLEO, simbolos_por_motor[Motor.NUCLEO], estrategias_nucleo),
        ConfigMotor(Motor.SATELITE, simbolos_por_motor[Motor.SATELITE], estrategias_satelite),
    ]

    # ------------------------------------------------------------------ bot
    intervalo = 5 if args.rapido else int(cfg.get("intervalo_seg", 60))
    bot = Bot(feed, broker, riesgo, store, motores, intervalo_seg=intervalo)

    puerto = int(cfg.get("puerto_dashboard", 8080))
    host = cfg.get("host_dashboard", "127.0.0.1")
    servir(bot, store, puerto=puerto, host=host)

    print(f"""
  Dashboard:  http://localhost:{puerto}
  Base datos: {args.datos}
  Capital:    nucleo {cap_nucleo} + satelite {cap_satelite} USDT (VIRTUALES)
  Ciclo:      cada {intervalo} s
  Exploracion:{' activada' if cfg.get('exploracion') else ' desactivada'}

  Ctrl+C para parar.
""")

    def parar(_sig, _frm):
        print("\nParando...")
        bot.detener()
        store.cerrar()
        sys.exit(0)

    signal.signal(signal.SIGINT, parar)
    signal.signal(signal.SIGTERM, parar)

    bot.correr()
    return 0


if __name__ == "__main__":
    sys.exit(main())
