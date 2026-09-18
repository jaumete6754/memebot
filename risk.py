"""Gestor de riesgo con derecho de veto.

Se sienta entre la estrategia y la ejecucion. La estrategia PROPONE; esto
DISPONE. Ninguna orden llega al broker sin pasar por aqui.

Las reglas son limites duros implementados en codigo. El bot no puede
modificarlos en caliente: si un sistema puede subirse sus propios limites, no
tiene limites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from modelo import Motor, Posicion


@dataclass
class LimitesMotor:
    """Limites de un motor concreto."""

    capital_inicial: Decimal
    max_posiciones: int = 4
    importe_por_operacion: Decimal = Decimal("10")
    max_drawdown_pct: Decimal = Decimal("35")     # sobre el capital inicial
    max_perdida_diaria_pct: Decimal = Decimal("15")
    min_nocional: Decimal = Decimal("5")          # minimo tipico de Binance spot
    max_exposicion_pct: Decimal = Decimal("80")   # % del capital en posiciones


@dataclass
class Veredicto:
    permitido: bool
    motivo: str = ""


@dataclass
class GestorRiesgo:
    limites: dict[Motor, LimitesMotor]
    store: object = None
    _parados: set = field(default_factory=set)   # motores detenidos por drawdown

    # ------------------------------------------------------------- consultas

    def esta_parado(self, motor: Motor) -> bool:
        return motor in self._parados

    def parar(self, motor: Motor, motivo: str) -> None:
        """Kill-switch. Solo se revierte con intervencion humana."""
        if motor not in self._parados:
            self._parados.add(motor)
            if self.store:
                self.store.incidente("kill_switch", f"{motor.value}: {motivo}", "critico")

    def reanudar(self, motor: Motor) -> None:
        """Reanudar es una accion HUMANA. El bot nunca se llama a si mismo aqui."""
        self._parados.discard(motor)
        if self.store:
            self.store.incidente("reanudado", f"{motor.value} reanudado a mano", "aviso")

    # ------------------------------------------------------------ evaluacion

    def puede_entrar(
        self,
        motor: Motor,
        importe: Decimal,
        saldo: Decimal,
        posiciones: list[Posicion],
        valor_posiciones: Decimal,
    ) -> Veredicto:
        lim = self.limites[motor]

        if self.esta_parado(motor):
            return Veredicto(False, "motor detenido por kill-switch")

        # REGLA DE HIERRO: el satelite jamas se recarga desde el nucleo.
        # Aqui se materializa: solo se mira el saldo de SU motor.
        if importe > saldo:
            return Veredicto(False, f"saldo insuficiente ({saldo:.2f})")

        if importe < lim.min_nocional:
            return Veredicto(
                False, f"por debajo del minimo nocional ({lim.min_nocional})"
            )

        abiertas = [p for p in posiciones if p.motor is motor]
        if len(abiertas) >= lim.max_posiciones:
            return Veredicto(False, f"maximo de posiciones alcanzado ({lim.max_posiciones})")

        equity = saldo + valor_posiciones
        exposicion = valor_posiciones + importe
        if equity > 0 and exposicion / equity * Decimal("100") > lim.max_exposicion_pct:
            return Veredicto(False, f"excede exposicion maxima ({lim.max_exposicion_pct}%)")

        return Veredicto(True)

    def revisar_drawdown(self, motor: Motor, equity: Decimal) -> Optional[str]:
        """Comprueba el drawdown total y para el motor si se pasa del limite."""
        lim = self.limites[motor]
        if lim.capital_inicial <= 0:
            return None
        caida = (lim.capital_inicial - equity) / lim.capital_inicial * Decimal("100")
        if caida >= lim.max_drawdown_pct:
            motivo = f"drawdown {caida:.1f}% >= limite {lim.max_drawdown_pct}%"
            self.parar(motor, motivo)
            return motivo
        return None

    def importe_operacion(self, motor: Motor, saldo: Decimal) -> Decimal:
        """Tamano de la siguiente entrada, acotado por el saldo disponible."""
        lim = self.limites[motor]
        return min(lim.importe_por_operacion, saldo)
