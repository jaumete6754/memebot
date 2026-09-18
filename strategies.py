"""Estrategias.

Cada estrategia es un plugin intercambiable: mira las velas y devuelve una
senal. No sabe nada de dinero, ni de brokers, ni de riesgo. Eso permite
cambiarlas sin tocar el resto del sistema.

Incluye un modo EXPLORACION que entra mucho y se equivoca mucho a proposito.
Con dinero virtual los errores son gratis y generan datos variados, que es lo
que la capa de aprendizaje necesita para poder comparar nada.

Aviso importante: las operaciones de exploracion se marcan como tales. Sus
resultados NO miden si una estrategia es buena, miden como se comporta el
mercado cuando entras sin criterio. Mezclar ambas cosas seria enganarse.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from modelo import Vela


@dataclass
class Senal:
    """Lo que una estrategia propone. El gestor de riesgo decide si se hace."""

    accion: str                     # "entrar" | "esperar"
    regla: str                      # nombre de la regla, para las estadisticas
    motivo: str                     # explicacion legible
    tp_pct: Decimal = Decimal("6")
    sl_pct: Decimal = Decimal("4")
    trailing_pct: Optional[Decimal] = None
    minutos_max: Optional[int] = None
    exploracion: bool = False
    contexto: dict = field(default_factory=dict)


# ------------------------------------------------------------- indicadores

def sma(velas: list[Vela], n: int) -> Optional[Decimal]:
    if len(velas) < n:
        return None
    return sum((v.cierre for v in velas[-n:]), Decimal("0")) / Decimal(n)


def volatilidad_pct(velas: list[Vela], n: int = 20) -> Decimal:
    """Media del recorrido de las ultimas n velas. Proxy barato de volatilidad."""
    if len(velas) < n:
        return Decimal("0")
    rangos = [v.rango_pct for v in velas[-n:]]
    return sum(rangos, Decimal("0")) / Decimal(len(rangos))


def regimen(velas: list[Vela]) -> str:
    """Clasifica el mercado. Sirve para saber DONDE funciona cada regla."""
    v = volatilidad_pct(velas)
    rapida, lenta = sma(velas, 10), sma(velas, 50)
    if rapida is None or lenta is None:
        return "desconocido"
    tendencia = "alcista" if rapida > lenta else "bajista"
    nivel = "volatil" if v > Decimal("1.0") else "tranquilo"
    return f"{tendencia}_{nivel}"


# -------------------------------------------------------------- estrategias

class Estrategia:
    nombre = "base"

    def evaluar(self, simbolo: str, velas: list[Vela], precio: Decimal) -> Senal:
        raise NotImplementedError


class CruceMedias(Estrategia):
    """Cruce de medias moviles. Estrategia de referencia, no de produccion.

    Esta aqui como LINEA BASE a batir. Si una estrategia compleja no le gana a
    esto ni a comprar y esperar, no tienes nada.
    """

    nombre = "cruce_medias"

    def __init__(self, rapida: int = 10, lenta: int = 50):
        self.rapida, self.lenta = rapida, lenta

    def evaluar(self, simbolo: str, velas: list[Vela], precio: Decimal) -> Senal:
        ctx = {"regimen": regimen(velas), "vol_pct": str(volatilidad_pct(velas))}

        if len(velas) < self.lenta + 2:
            return Senal("esperar", self.nombre, "historial insuficiente", contexto=ctx)

        r_ahora, l_ahora = sma(velas, self.rapida), sma(velas, self.lenta)
        r_antes = sma(velas[:-1], self.rapida)
        l_antes = sma(velas[:-1], self.lenta)
        if None in (r_ahora, l_ahora, r_antes, l_antes):
            return Senal("esperar", self.nombre, "medias no calculables", contexto=ctx)

        ctx.update({"sma_rapida": str(r_ahora), "sma_lenta": str(l_ahora)})

        cruce_alcista = r_antes <= l_antes and r_ahora > l_ahora
        if cruce_alcista:
            return Senal(
                "entrar", self.nombre,
                f"cruce alcista: SMA{self.rapida} supera a SMA{self.lenta}",
                tp_pct=Decimal("6"), sl_pct=Decimal("4"),
                trailing_pct=Decimal("3"), minutos_max=60 * 24,
                contexto=ctx,
            )
        return Senal("esperar", self.nombre, "sin cruce", contexto=ctx)


class RupturaVolumen(Estrategia):
    """Ruptura de maximos recientes acompanada de volumen.

    Segunda regla real, para que la capa de aprendizaje tenga algo que comparar.
    """

    nombre = "ruptura_volumen"

    def __init__(self, ventana: int = 30, factor_vol: Decimal = Decimal("1.8")):
        self.ventana, self.factor_vol = ventana, factor_vol

    def evaluar(self, simbolo: str, velas: list[Vela], precio: Decimal) -> Senal:
        ctx = {"regimen": regimen(velas), "vol_pct": str(volatilidad_pct(velas))}

        if len(velas) < self.ventana + 1:
            return Senal("esperar", self.nombre, "historial insuficiente", contexto=ctx)

        previas = velas[-(self.ventana + 1):-1]
        max_previo = max(v.maximo for v in previas)
        vol_media = sum((v.volumen for v in previas), Decimal("0")) / Decimal(len(previas))
        vol_actual = velas[-1].volumen

        ctx.update({"max_previo": str(max_previo), "vol_ratio":
                    str(vol_actual / vol_media) if vol_media > 0 else "0"})

        if precio > max_previo and vol_media > 0 and vol_actual > vol_media * self.factor_vol:
            return Senal(
                "entrar", self.nombre,
                f"ruptura de maximo de {self.ventana} velas con volumen alto",
                tp_pct=Decimal("8"), sl_pct=Decimal("4"),
                trailing_pct=Decimal("3"), minutos_max=60 * 12,
                contexto=ctx,
            )
        return Senal("esperar", self.nombre, "sin ruptura", contexto=ctx)


class Exploracion(Estrategia):
    """Modo exploracion: entra mucho, en muchos sitios, y se equivoca a menudo.

    Para que sirve de verdad: genera datos variados sobre como se comporta el
    mercado. Con dinero virtual el error es gratis.

    Para que NO sirve: para deducir que es rentable. Entrar casi al azar produce
    resultados dominados por el ruido. Ademas, las memecoins estan MUY
    correlacionadas entre si: tener 8 posiciones abiertas a la vez no son 8
    muestras independientes, es practicamente la misma apuesta repetida.
    """

    nombre = "exploracion"

    def __init__(self, prob_entrada: float = 0.12, semilla: int = 7):
        self.prob = prob_entrada
        self.rng = random.Random(semilla)

    def evaluar(self, simbolo: str, velas: list[Vela], precio: Decimal) -> Senal:
        ctx = {"regimen": regimen(velas), "vol_pct": str(volatilidad_pct(velas))}

        if len(velas) < 20:
            return Senal("esperar", self.nombre, "historial insuficiente", contexto=ctx)

        if self.rng.random() >= self.prob:
            return Senal("esperar", self.nombre, "sin entrada en este ciclo",
                         contexto=ctx)

        # Parametros variados a proposito: asi se puede aprender que combinacion
        # de objetivo y stop aguanta mejor en cada regimen de mercado.
        tp = Decimal(str(self.rng.choice([3, 5, 8, 12, 20])))
        sl = Decimal(str(self.rng.choice([2, 3, 5, 8])))
        mins = self.rng.choice([30, 120, 360, 1440])
        ctx.update({"tp_sorteado": str(tp), "sl_sorteado": str(sl)})

        return Senal(
            "entrar", self.nombre,
            f"exploracion: objetivo {tp}% / stop {sl}% / limite {mins} min",
            tp_pct=tp, sl_pct=sl,
            trailing_pct=Decimal("3") if self.rng.random() < 0.5 else None,
            minutos_max=mins, exploracion=True, contexto=ctx,
        )
