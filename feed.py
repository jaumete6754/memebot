"""Feeds de mercado.

Dos implementaciones detras de la misma interfaz:

  FeedBinance    - precios REALES de Binance, solo endpoints publicos (sin claves)
  FeedSintetico  - camino aleatorio con volatilidad tipo memecoin, para pruebas
                   sin conexion

El bot no sabe cual esta usando. Esa es justo la propiedad que permite que el
codigo que se prueba sea exactamente el que opera.

Se usa REST con sondeo en vez de WebSocket a proposito: cero dependencias (solo
urllib de la libreria estandar), lo que significa que en Termux se instala sin
compilar nada. Para marcos temporales de minutos a dias el sondeo es de sobra;
un WebSocket solo hace falta si operas en segundos, que no es el caso.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional

from modelo import Vela, ahora_ms

# Binance publica los mismos datos en varios hosts. Si uno falla o esta
# bloqueado geograficamente, probamos el siguiente. data-api.binance.vision es
# el endpoint publico de datos de mercado: sin clave y sin restricciones de
# cuenta.
HOSTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
]

USER_AGENT = "memebot/0.1 (proyecto educativo)"


class ErrorFeed(Exception):
    """El feed no pudo obtener datos. El motor lo registra y reintenta."""


class Feed(ABC):
    """Interfaz comun. El bot solo conoce esto."""

    @abstractmethod
    def precios(self, simbolos: list[str]) -> dict[str, Decimal]:
        """Precio actual de cada simbolo."""

    @abstractmethod
    def velas(self, simbolo: str, intervalo: str = "1m", limite: int = 200) -> list[Vela]:
        """Velas historicas, de mas antigua a mas reciente."""

    @property
    def es_real(self) -> bool:
        return False


class FeedBinance(Feed):
    """Datos reales de Binance por REST publico.

    Nunca necesita una clave de API: todos los endpoints usados son publicos.
    """

    def __init__(self, timeout: int = 10, reintentos: int = 3, store=None):
        self.timeout = timeout
        self.reintentos = reintentos
        self.store = store           # opcional, para registrar incidentes
        self._host_ok: Optional[str] = None
        self.ultima_lectura_ms: int = 0

    @property
    def es_real(self) -> bool:
        return True

    # ------------------------------------------------------------- transporte

    def _get(self, ruta: str, params: dict) -> object:
        """GET con failover entre hosts y reintentos con espera creciente."""
        qs = urllib.parse.urlencode(params)
        # Empezamos por el host que funciono la ultima vez.
        hosts = HOSTS if self._host_ok is None else (
            [self._host_ok] + [h for h in HOSTS if h != self._host_ok]
        )
        ultimo_error = ""

        for intento in range(self.reintentos):
            for host in hosts:
                url = f"{host}{ruta}?{qs}"
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout) as r:
                        datos = json.loads(r.read().decode())
                    if host != self._host_ok:
                        if self._host_ok is not None and self.store:
                            self.store.incidente(
                                "feed_failover", f"cambiado a {host}", "aviso"
                            )
                        self._host_ok = host
                    self.ultima_lectura_ms = ahora_ms()
                    return datos
                except urllib.error.HTTPError as e:
                    ultimo_error = f"{host} HTTP {e.code}"
                    # 418/429 = rate limit de Binance. Esperar mas y no insistir.
                    if e.code in (418, 429):
                        time.sleep(5 * (intento + 1))
                except Exception as e:  # noqa: BLE001 - queremos capturar todo
                    ultimo_error = f"{host} {type(e).__name__}: {e}"
            time.sleep(2 ** intento)

        if self.store:
            self.store.incidente("feed_caido", ultimo_error, "error")
        raise ErrorFeed(ultimo_error)

    # ----------------------------------------------------------------- datos

    def precios(self, simbolos: list[str]) -> dict[str, Decimal]:
        if not simbolos:
            return {}
        datos = self._get(
            "/api/v3/ticker/price", {"symbols": json.dumps(simbolos, separators=(",", ":"))}
        )
        return {d["symbol"]: Decimal(d["price"]) for d in datos}

    def velas(self, simbolo: str, intervalo: str = "1m", limite: int = 200) -> list[Vela]:
        datos = self._get(
            "/api/v3/klines",
            {"symbol": simbolo, "interval": intervalo, "limit": min(limite, 1000)},
        )
        return [
            Vela(
                simbolo=simbolo,
                apertura_ms=int(k[0]),
                apertura=Decimal(k[1]),
                maximo=Decimal(k[2]),
                minimo=Decimal(k[3]),
                cierre=Decimal(k[4]),
                volumen=Decimal(k[5]),
            )
            for k in datos
        ]

    def filtros_simbolo(self, simbolo: str) -> dict:
        """Minimo nocional y paso de cantidad, leidos del exchange.

        Nunca se asumen: varian por par y cambian con el tiempo.
        """
        datos = self._get("/api/v3/exchangeInfo", {"symbol": simbolo})
        info = datos["symbols"][0]
        salida = {"minNotional": Decimal("5"), "stepSize": Decimal("0.00000001")}
        for f in info["filters"]:
            if f["filterType"] in ("NOTIONAL", "MIN_NOTIONAL"):
                salida["minNotional"] = Decimal(f.get("minNotional", "5"))
            elif f["filterType"] == "LOT_SIZE":
                salida["stepSize"] = Decimal(f["stepSize"])
        return salida


class FeedSintetico(Feed):
    """Camino aleatorio con volatilidad de memecoin. Solo para pruebas locales.

    No pretende parecerse al mercado real: sirve para comprobar que la
    fontaneria funciona (entradas, salidas, registro, dashboard) sin necesidad
    de conexion. Cualquier resultado que produzca es, literalmente, ruido.
    """

    def __init__(self, simbolos: list[str], semilla: int = 42, vol_pct: float = 1.2):
        self.rng = random.Random(semilla)
        self.vol = vol_pct
        self._precios: dict[str, Decimal] = {}
        self._historia: dict[str, list[Vela]] = {}
        base = {"PEPEUSDT": "0.00000900", "DOGEUSDT": "0.0840",
                "SHIBUSDT": "0.00001200", "BONKUSDT": "0.00001800"}
        for s in simbolos:
            self._precios[s] = Decimal(base.get(s, "1.0"))
            self._historia[s] = []
            self._precalentar(s, 300)

    def _siguiente(self, simbolo: str) -> Decimal:
        p = float(self._precios[simbolo])
        # Deriva ligeramente negativa: las memecoins tienden a bajar a largo plazo.
        deriva = -0.0004
        p *= (1 + self.rng.gauss(deriva, self.vol / 100))
        p = max(p, 1e-12)
        self._precios[simbolo] = Decimal(f"{p:.12f}")
        return self._precios[simbolo]

    def _precalentar(self, simbolo: str, n: int) -> None:
        t = ahora_ms() - n * 60_000
        for i in range(n):
            c = self._siguiente(simbolo)
            self._historia[simbolo].append(self._vela(simbolo, t + i * 60_000, c))

    def _vela(self, simbolo: str, t: int, cierre: Decimal) -> Vela:
        f = float(cierre)
        hi = Decimal(f"{f * (1 + abs(self.rng.gauss(0, 0.004))):.12f}")
        lo = Decimal(f"{f * (1 - abs(self.rng.gauss(0, 0.004))):.12f}")
        return Vela(simbolo, t, cierre, hi, lo, cierre,
                    Decimal(f"{self.rng.uniform(1e5, 9e5):.2f}"))

    def precios(self, simbolos: list[str]) -> dict[str, Decimal]:
        salida = {}
        for s in simbolos:
            c = self._siguiente(s)
            self._historia.setdefault(s, []).append(
                self._vela(s, ahora_ms(), c)
            )
            salida[s] = c
        return salida

    def velas(self, simbolo: str, intervalo: str = "1m", limite: int = 200) -> list[Vela]:
        return self._historia.get(simbolo, [])[-limite:]
