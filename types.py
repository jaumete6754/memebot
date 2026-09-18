"""Tipos base del sistema.

Todo el dinero se representa con Decimal, nunca con float: los errores de
redondeo en coma flotante se acumulan operacion tras operacion y acaban
descuadrando el saldo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


def ahora_ms() -> int:
    """Timestamp actual en milisegundos UTC."""
    return int(time.time() * 1000)


class Motor(str, Enum):
    """Los dos motores del sistema, con presupuestos separados."""

    NUCLEO = "nucleo"      # Pares liquidos con historial: DOGE, SHIB, PEPE, BONK
    SATELITE = "satelite"  # Alto riesgo. Nunca se recarga desde el nucleo.


class Lado(str, Enum):
    COMPRA = "compra"
    VENTA = "venta"


class MotivoSalida(str, Enum):
    """Por que se cerro una posicion. Clave para el analisis posterior."""

    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    TIEMPO_AGOTADO = "tiempo_agotado"   # El reloj de la viralidad se acabo
    SENAL_ESTRATEGIA = "senal_estrategia"
    PARADA_EMERGENCIA = "parada_emergencia"


@dataclass(frozen=True)
class Vela:
    """Una vela OHLCV. Inmutable a proposito."""

    simbolo: str
    apertura_ms: int
    apertura: Decimal
    maximo: Decimal
    minimo: Decimal
    cierre: Decimal
    volumen: Decimal

    @property
    def rango_pct(self) -> Decimal:
        """Recorrido de la vela en porcentaje. Proxy barato de volatilidad."""
        if self.minimo <= 0:
            return Decimal("0")
        return (self.maximo - self.minimo) / self.minimo * Decimal("100")


@dataclass
class Posicion:
    """Una posicion abierta. El bot solo opera en largo (spot, sin apalancamiento)."""

    id: int
    motor: Motor
    simbolo: str
    cantidad: Decimal
    precio_entrada: Decimal
    entrada_ms: int
    stop_loss: Decimal
    take_profit: Decimal
    stop_inicial: Decimal = Decimal("0")   # para saber si el trailing llego a moverlo
    trailing_pct: Optional[Decimal] = None
    max_precio_visto: Decimal = Decimal("0")
    limite_tiempo_ms: Optional[int] = None
    regla: str = ""              # Que regla la abrio. Se usa para las estadisticas.
    comision_entrada: Decimal = Decimal("0")

    def valor(self, precio: Decimal) -> Decimal:
        return self.cantidad * precio

    def pnl_no_realizado(self, precio: Decimal) -> Decimal:
        return (precio - self.precio_entrada) * self.cantidad

    def pnl_pct(self, precio: Decimal) -> Decimal:
        if self.precio_entrada <= 0:
            return Decimal("0")
        return (precio - self.precio_entrada) / self.precio_entrada * Decimal("100")


@dataclass
class Operacion:
    """Una operacion ya cerrada: entrada, salida y resultado."""

    motor: Motor
    simbolo: str
    cantidad: Decimal
    precio_entrada: Decimal
    precio_salida: Decimal
    entrada_ms: int
    salida_ms: int
    motivo_salida: MotivoSalida
    regla: str
    comisiones: Decimal
    pnl: Decimal                      # Neto, ya descontadas comisiones
    pnl_pct: Decimal
    # Lo que el bot esperaba cuando entro, para comparar con lo que paso
    tp_esperado_pct: Decimal = Decimal("0")
    sl_esperado_pct: Decimal = Decimal("0")
    regimen: str = "desconocido"   # regimen de mercado en el momento de entrar
    id: Optional[int] = None

    @property
    def es_exploracion(self) -> bool:
        return self.regla == "exploracion"

    @property
    def duracion_min(self) -> float:
        return (self.salida_ms - self.entrada_ms) / 60000.0

    @property
    def acierto(self) -> bool:
        return self.pnl > 0


@dataclass
class Decision:
    """Registro de CADA decision, incluidas las de no hacer nada.

    Guardamos el contexto completo del momento, no solo el precio. Sin esto no
    se puede reconstruir por que el bot hizo lo que hizo, ni reevaluar
    configuraciones alternativas sobre datos reales.
    """

    ts_ms: int
    motor: Motor
    simbolo: str
    accion: str                        # "entrar", "salir", "esperar"
    regla: str
    motivo: str
    precio: Decimal
    contexto: dict = field(default_factory=dict)
    version_config: str = "v1"
    id: Optional[int] = None


@dataclass
class Incidente:
    """Fallo operativo: caida, reconexion, dato corrupto, orden rechazada."""

    ts_ms: int
    tipo: str
    detalle: str
    severidad: str = "aviso"   # aviso | error | critico
