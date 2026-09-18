"""Brokers: la unica frontera entre el bot y el dinero.

La estrategia nunca sabe que implementacion hay detras. Cambiar de papel a real
es cambiar que objeto se inyecta, nada mas. Si algun dia hiciera falta tocar
cualquier otra cosa para pasar a real, el paper trading estaria mintiendo.

BrokerPapel simula los llenados de forma DELIBERADAMENTE PESIMISTA. El paper
trading es optimista por naturaleza porque no modela la posicion en la cola del
libro ni el impacto de mercado, asi que compensamos al alza. Mejor que la
realidad sorprenda para bien.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional

from modelo import Lado, Motor, ahora_ms


class ErrorBroker(Exception):
    pass


class Broker(ABC):
    """Interfaz comun a papel y real."""

    @abstractmethod
    def comprar(self, motor: Motor, simbolo: str, importe: Decimal,
                precio: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        """Compra por importe. Devuelve (cantidad, precio_ejecutado, comision)."""

    @abstractmethod
    def vender(self, motor: Motor, simbolo: str, cantidad: Decimal,
               precio: Decimal) -> tuple[Decimal, Decimal]:
        """Vende cantidad. Devuelve (precio_ejecutado, comision)."""

    @abstractmethod
    def saldo(self, motor: Motor) -> Decimal:
        """Efectivo disponible de ese motor."""

    @property
    def es_real(self) -> bool:
        return False


class BrokerPapel(Broker):
    """Simulacion con dinero virtual sobre precios reales.

    Parametros pesimistas por defecto:
      comision 0.1% por lado  -> tarifa spot estandar de Binance
      slippage 0.15%          -> peor de lo que normalmente veras en pares liquidos
    """

    def __init__(
        self,
        saldos: dict[Motor, Decimal],
        comision_pct: Decimal = Decimal("0.1"),
        slippage_pct: Decimal = Decimal("0.15"),
        store=None,
    ):
        self._saldos = dict(saldos)
        self._saldos_iniciales = dict(saldos)
        self.comision_pct = comision_pct
        self.slippage_pct = slippage_pct
        self.store = store
        if store is not None:
            guardado = store.get_estado("saldos")
            if guardado:
                self._saldos = {Motor(k): Decimal(v) for k, v in guardado.items()}

    # ----------------------------------------------------------------- saldo

    def saldo(self, motor: Motor) -> Decimal:
        return self._saldos.get(motor, Decimal("0"))

    def saldo_inicial(self, motor: Motor) -> Decimal:
        return self._saldos_iniciales.get(motor, Decimal("0"))

    def _persistir(self) -> None:
        if self.store is not None:
            self.store.set_estado(
                "saldos", {m.value: str(v) for m, v in self._saldos.items()}
            )

    # -------------------------------------------------------------- ordenes

    def _precio_con_slippage(self, precio: Decimal, lado: Lado) -> Decimal:
        """Siempre en tu contra: compras mas caro, vendes mas barato."""
        desliz = precio * self.slippage_pct / Decimal("100")
        return precio + desliz if lado is Lado.COMPRA else precio - desliz

    def comprar(self, motor: Motor, simbolo: str, importe: Decimal,
                precio: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        if importe <= 0:
            raise ErrorBroker("importe debe ser positivo")
        if importe > self.saldo(motor):
            raise ErrorBroker(
                f"saldo insuficiente en {motor.value}: "
                f"pide {importe}, hay {self.saldo(motor)}"
            )

        precio_eje = self._precio_con_slippage(precio, Lado.COMPRA)
        comision = importe * self.comision_pct / Decimal("100")
        neto = importe - comision
        cantidad = neto / precio_eje

        self._saldos[motor] = self.saldo(motor) - importe
        self._persistir()
        return cantidad, precio_eje, comision

    def vender(self, motor: Motor, simbolo: str, cantidad: Decimal,
               precio: Decimal) -> tuple[Decimal, Decimal]:
        if cantidad <= 0:
            raise ErrorBroker("cantidad debe ser positiva")

        precio_eje = self._precio_con_slippage(precio, Lado.VENTA)
        bruto = cantidad * precio_eje
        comision = bruto * self.comision_pct / Decimal("100")
        neto = bruto - comision

        self._saldos[motor] = self.saldo(motor) + neto
        self._persistir()
        return precio_eje, comision


class BrokerReal(Broker):
    """Sin implementar a proposito.

    Cuando llegue el momento, esta clase leera las claves de variables de
    entorno (nunca del codigo, nunca de un fichero versionado) y la clave DEBE
    tener el permiso de retirada DESACTIVADO y whitelist de IP activa.

    No se implementa ahora porque no hace falta: las semanas de construccion y
    de paper trading funcionan integras sin que exista ninguna credencial.
    """

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError(
            "El modo real no esta implementado. Se activara solo cuando se "
            "cumplan los criterios de salida definidos en el plan."
        )

    def comprar(self, *_a, **_k):
        raise NotImplementedError

    def vender(self, *_a, **_k):
        raise NotImplementedError

    def saldo(self, *_a, **_k):
        raise NotImplementedError
