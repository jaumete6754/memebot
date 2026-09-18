"""Capa de aprendizaje.

Dos cosas distintas, y conviene no confundirlas:

1. LECCION POR OPERACION. En cuanto una posicion se cierra se escribe que
   esperaba el bot, que paso en realidad y que se deduce de la diferencia. Es
   lo que aparece en la app despues de cada operacion.

2. ESTADISTICAS ACUMULADAS. Agregados por regla, por regimen de mercado y por
   motivo de salida, SIEMPRE con el numero de muestras delante.

La regla de honestidad de este modulo: nunca presentar como conclusion algo que
la muestra no soporta. Una racha de 5 operaciones no ensena nada, y un sistema
que afirma haber "aprendido" de 5 operaciones esta haciendo dano, no analisis.
Por eso cada conclusion lleva su n y su margen de error.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from modelo import MotivoSalida, Operacion

# Umbrales de tamano muestral. No son magia: por debajo de 30 el intervalo de
# confianza de una proporcion es tan ancho que casi cualquier valor cabe dentro.
MIN_ORIENTATIVO = 30
MIN_FIABLE = 100


@dataclass
class Leccion:
    titulo: str
    texto: str
    tipo: str          # "bueno" | "malo" | "neutro"


def leccion_de_operacion(op: Operacion) -> Leccion:
    """Que se aprende de UNA operacion concreta.

    Ojo: de una sola operacion se aprende sobre la EJECUCION (si el stop era
    razonable, si el objetivo era alcanzable), nunca sobre si la estrategia es
    rentable. Eso solo lo dice la agregacion.
    """
    dur = op.duracion_min
    if dur < 1:
        dur_txt = f"{dur * 60:.0f} s"
    elif dur < 120:
        dur_txt = f"{dur:.0f} min"
    else:
        dur_txt = f"{dur / 60:.1f} h"
    volatil = "volatil" in op.regimen

    if op.motivo_salida is MotivoSalida.TAKE_PROFIT:
        return Leccion(
            "Objetivo alcanzado",
            f"Subio hasta el objetivo del {op.tp_esperado_pct}% en {dur_txt}. "
            f"Resultado neto {op.pnl_pct:+.2f}% tras comisiones "
            f"({op.comisiones:.4f} USDT). La diferencia entre el objetivo y el "
            f"neto es lo que se lleva el coste de operar.",
            "bueno",
        )

    if op.motivo_salida is MotivoSalida.TRAILING_STOP:
        if op.pnl > 0:
            return Leccion(
                "Recogido por trailing stop",
                f"El precio subio, el trailing acompano y la ganancia se cerro en "
                f"{op.pnl_pct:+.2f}% tras {dur_txt}. Queda registrado para poder "
                f"comparar despues si el trailing ayuda o recorta demasiado pronto.",
                "bueno",
            )
        return Leccion(
            "Trailing stop con perdida",
            f"El precio llego a subir y el trailing movio el stop, pero al girarse "
            f"cerro en {op.pnl_pct:+.2f}% tras {dur_txt}. Es el caso que mas ensena: "
            f"la subida no fue suficiente para cubrir el coste de entrar y salir "
            f"({op.comisiones:.4f} USDT entre comisiones y slippage). Con un "
            f"trailing del {op.sl_esperado_pct}% hace falta un recorrido mayor "
            f"antes de que proteger tenga sentido.",
            "malo",
        )

    if op.motivo_salida is MotivoSalida.STOP_LOSS:
        partes = [
            f"Cayo hasta el stop del {op.sl_esperado_pct}% en {dur_txt}. "
            f"Perdida neta {op.pnl_pct:+.2f}%."
        ]
        # La diferencia entre el stop nominal y la perdida real es el coste de
        # operar. Verlo en cada operacion es la leccion mas util del sistema.
        hueco = abs(op.pnl_pct) - op.sl_esperado_pct
        if hueco > Decimal("0.3"):
            partes.append(
                f"Perdiste {hueco:.2f} puntos MAS que el stop nominal: esa "
                f"diferencia son comisiones y slippage ({op.comisiones:.4f} USDT). "
                f"Es el coste de operar, y se paga en cada ida y vuelta."
            )
        if volatil and op.sl_esperado_pct < Decimal("5"):
            partes.append(
                f"Ademas, un stop del {op.sl_esperado_pct}% es estrecho para un "
                f"regimen volatil: probablemente lo tumbo el ruido normal del "
                f"mercado y no un giro real."
            )
        return Leccion("Stop loss ejecutado", " ".join(partes), "malo")

    if op.motivo_salida is MotivoSalida.TIEMPO_AGOTADO:
        return Leccion(
            "Cerrado por tiempo",
            f"En {dur_txt} no llego ni al objetivo ni al stop, asi que se cerro "
            f"por limite de tiempo con {op.pnl_pct:+.2f}%. Las entradas que "
            f"acaban asi suelen indicar que la senal no tenia fuerza: no estaba "
            f"equivocada, estaba vacia.",
            "neutro",
        )

    return Leccion(
        "Posicion cerrada",
        f"Cierre por {op.motivo_salida.value} con {op.pnl_pct:+.2f}% en {dur_txt}.",
        "bueno" if op.pnl > 0 else "malo",
    )


# --------------------------------------------------------------- agregados

def _margen_proporcion(aciertos: int, n: int) -> float:
    """Margen de error al 95% de una proporcion. Es lo que hace honesta la cifra."""
    if n == 0:
        return 0.0
    p = aciertos / n
    return 1.96 * math.sqrt(max(p * (1 - p), 1e-9) / n) * 100


def _resumen(ops: list[Operacion]) -> dict:
    n = len(ops)
    if n == 0:
        return {"n": 0, "aciertos": 0, "tasa": 0.0, "margen": 0.0,
                "pnl": Decimal("0"), "pnl_medio": Decimal("0"),
                "comisiones": Decimal("0"), "duracion_media_min": 0.0}
    aciertos = sum(1 for o in ops if o.acierto)
    pnl = sum((o.pnl for o in ops), Decimal("0"))
    comis = sum((o.comisiones for o in ops), Decimal("0"))
    return {
        "n": n,
        "aciertos": aciertos,
        "tasa": aciertos / n * 100,
        "margen": _margen_proporcion(aciertos, n),
        "pnl": pnl,
        "pnl_medio": pnl / Decimal(n),
        "comisiones": comis,
        "duracion_media_min": sum(o.duracion_min for o in ops) / n,
    }


def _agrupar(ops: Iterable[Operacion], clave) -> dict[str, dict]:
    grupos: dict[str, list[Operacion]] = defaultdict(list)
    for o in ops:
        grupos[clave(o)].append(o)
    return {k: _resumen(v) for k, v in sorted(grupos.items())}


class Aprendizaje:
    """Calcula lo que el sistema sabe hasta ahora a partir del historial."""

    def __init__(self, store):
        self.store = store

    def informe(self, limite: int = 2000) -> dict:
        ops = self.store.operaciones(limite=limite)
        estrategia = [o for o in ops if not o.es_exploracion]
        explora = [o for o in ops if o.es_exploracion]

        return {
            "global": _resumen(ops),
            "estrategia": _resumen(estrategia),
            "exploracion": _resumen(explora),
            "por_regla": _agrupar(ops, lambda o: o.regla),
            "por_regimen": _agrupar(ops, lambda o: o.regimen),
            "por_salida": _agrupar(ops, lambda o: o.motivo_salida.value),
            "por_simbolo": _agrupar(ops, lambda o: o.simbolo),
            "peso_comisiones": self._peso_comisiones(ops),
            "conclusiones": self.conclusiones(ops),
        }

    @staticmethod
    def _peso_comisiones(ops: list[Operacion]) -> dict:
        """Cuanto se come el coste de operar. Es lo que mata a las cuentas pequenas."""
        if not ops:
            return {"comisiones": Decimal("0"), "bruto_positivo": Decimal("0"),
                    "porcentaje": 0.0}
        comis = sum((o.comisiones for o in ops), Decimal("0"))
        bruto = sum((o.pnl + o.comisiones for o in ops if o.pnl + o.comisiones > 0),
                    Decimal("0"))
        pct = float(comis / bruto * 100) if bruto > 0 else 0.0
        return {"comisiones": comis, "bruto_positivo": bruto, "porcentaje": pct}

    def conclusiones(self, ops: list[Operacion]) -> list[dict]:
        """Hallazgos en lenguaje llano, con el tamano muestral SIEMPRE delante."""
        salida: list[dict] = []
        n = len(ops)

        if n < MIN_ORIENTATIVO:
            salida.append({
                "nivel": "insuficiente",
                "texto": (
                    f"Solo hay {n} operaciones cerradas. Por debajo de "
                    f"{MIN_ORIENTATIVO} no se puede concluir nada: el resultado "
                    f"esta dominado por el azar. Lo que ves ahora mide que el "
                    f"sistema funciona, no si gana dinero."
                ),
            })
            return salida

        res = _resumen(ops)
        nivel = "orientativo" if n < MIN_FIABLE else "razonable"
        salida.append({
            "nivel": nivel,
            "texto": (
                f"Con {n} operaciones, la tasa de acierto es "
                f"{res['tasa']:.1f}% +/- {res['margen']:.1f} puntos (95% de "
                f"confianza). El resultado acumulado es {res['pnl']:+.4f} USDT."
            ),
        })

        # Comparacion entre reglas, solo si ambas tienen muestra suficiente.
        por_regla = _agrupar(ops, lambda o: o.regla)
        comparables = {k: v for k, v in por_regla.items() if v["n"] >= MIN_ORIENTATIVO}
        if len(comparables) >= 2:
            mejor = max(comparables.items(), key=lambda kv: kv[1]["pnl_medio"])
            peor = min(comparables.items(), key=lambda kv: kv[1]["pnl_medio"])
            if mejor[0] != peor[0]:
                salida.append({
                    "nivel": nivel,
                    "texto": (
                        f"La regla '{mejor[0]}' ({mejor[1]['n']} ops) va mejor que "
                        f"'{peor[0]}' ({peor[1]['n']} ops): "
                        f"{mejor[1]['pnl_medio']:+.4f} frente a "
                        f"{peor[1]['pnl_medio']:+.4f} USDT por operacion. "
                        f"Con estas muestras es un indicio, no una conclusion."
                    ),
                })

        # El coste de operar.
        peso = self._peso_comisiones(ops)
        if peso["porcentaje"] > 30:
            salida.append({
                "nivel": "aviso",
                "texto": (
                    f"Las comisiones se llevan el {peso['porcentaje']:.0f}% de las "
                    f"ganancias brutas. Operar menos y con objetivos mas amplios "
                    f"mejoraria mas el resultado que acertar mas."
                ),
            })

        # Stops saltando en exceso.
        por_salida = _agrupar(ops, lambda o: o.motivo_salida.value)
        stops = por_salida.get(MotivoSalida.STOP_LOSS.value, {"n": 0})
        if stops["n"] / n > 0.5:
            salida.append({
                "nivel": "aviso",
                "texto": (
                    f"El {stops['n'] / n * 100:.0f}% de las operaciones acaban en "
                    f"stop loss. Suele significar stops demasiado estrechos para "
                    f"la volatilidad de estos pares, no que las entradas sean malas."
                ),
            })

        # Las de exploracion no miden estrategia.
        n_expl = sum(1 for o in ops if o.es_exploracion)
        if n_expl > 0:
            salida.append({
                "nivel": "nota",
                "texto": (
                    f"{n_expl} de las {n} operaciones son de exploracion (entradas "
                    f"sin criterio, a proposito). Sirven para generar datos "
                    f"variados, no para juzgar ninguna estrategia."
                ),
            })

        return salida
