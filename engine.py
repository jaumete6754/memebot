"""El motor: el bucle que lo une todo.

Un solo bot. Lo unico que cambia entre pruebas y real es que Feed y que Broker
se le inyectan. Esa es la propiedad que hace que el codigo probado sea
exactamente el codigo que opera.

Orden de cada ciclo:
  1. Leer precios
  2. Revisar posiciones abiertas (stop, objetivo, trailing, tiempo)  <- salir primero
  3. Buscar entradas nuevas
  4. Revisar drawdown y aplicar kill-switch si toca

Las salidas se evaluan ANTES que las entradas a proposito: si el capital esta
al limite, prefieres liberar una posicion perdedora antes que abrir otra.
"""

from __future__ import annotations

import threading
import time
import traceback
from decimal import Decimal
from typing import Optional

from broker import Broker, ErrorBroker
from feed import ErrorFeed, Feed
from learn import leccion_de_operacion
from risk import GestorRiesgo
from strategies import Estrategia, Senal, regimen
from store import Store
from modelo import (
    Decision,
    Motor,
    MotivoSalida,
    Operacion,
    Posicion,
    Vela,
    ahora_ms,
)


# Desvio maximo tolerable entre el precio de entrada de una posicion recuperada
# del disco y el precio de mercado actual. Por encima de esto, la posicion no es
# creible y se anula (ver _validar_recuperadas).
DESVIO_MAX_RECUPERACION = Decimal("0.40")


class ConfigMotor:
    def __init__(self, motor: Motor, simbolos: list[str], estrategias: list[Estrategia]):
        self.motor = motor
        self.simbolos = simbolos
        self.estrategias = estrategias


class Bot:
    def __init__(
        self,
        feed: Feed,
        broker: Broker,
        riesgo: GestorRiesgo,
        store: Store,
        motores: list[ConfigMotor],
        intervalo_seg: int = 60,
        version_config: str = "v1",
    ):
        self.feed = feed
        self.broker = broker
        self.riesgo = riesgo
        self.store = store
        self.motores = motores
        self.intervalo = intervalo_seg
        self.version_config = version_config

        self.posiciones: list[Posicion] = store.posiciones_abiertas()
        self.ultima_leccion: Optional[dict] = None
        self.ciclos = 0
        self.ultimo_ciclo_ms = 0
        self.arrancado_ms = ahora_ms()
        self._parar = threading.Event()
        self._cache_velas: dict[str, list[Vela]] = {}
        self._validadas = not self.posiciones

        if self.posiciones:
            store.incidente(
                "reinicio",
                f"recuperadas {len(self.posiciones)} posiciones abiertas del disco",
                "aviso",
            )

    # ------------------------------------------------------------------ util

    @property
    def simbolos(self) -> list[str]:
        vistos: list[str] = []
        for m in self.motores:
            for s in m.simbolos:
                if s not in vistos:
                    vistos.append(s)
        return vistos

    def equity(self, motor: Motor, precios: dict[str, Decimal]) -> Decimal:
        """Efectivo + valor de mercado de las posiciones de ese motor."""
        total = self.broker.saldo(motor)
        for p in self.posiciones:
            if p.motor is motor:
                total += p.valor(precios.get(p.simbolo, p.precio_entrada))
        return total

    def valor_posiciones(self, motor: Motor, precios: dict[str, Decimal]) -> Decimal:
        return sum(
            (p.valor(precios.get(p.simbolo, p.precio_entrada))
             for p in self.posiciones if p.motor is motor),
            Decimal("0"),
        )

    def _validar_recuperadas(self, precios: dict[str, Decimal]) -> None:
        """Anula posiciones recuperadas cuyo precio de entrada no cuadra con el mercado.

        INCIDENTE 001: al reutilizar la base de datos entre modos, el bot
        recupero posiciones abiertas a precios inventados y las cerro contra
        precios reales, generando perdidas falsas del -67%.

        La causa ya esta cubierta (una base de datos por modo). Esto es la
        segunda capa: si por lo que sea una posicion recuperada esta a un
        precio absurdo, se ANULA -- se devuelve el capital y se registra el
        incidente -- en vez de cerrarla y contaminar las estadisticas con una
        operacion que nunca existio.
        """
        for pos in list(self.posiciones):
            precio = precios.get(pos.simbolo)
            if precio is None or pos.precio_entrada <= 0:
                continue
            desvio = abs(precio - pos.precio_entrada) / pos.precio_entrada
            if desvio <= DESVIO_MAX_RECUPERACION:
                continue

            # Devolver el capital tal cual entro: la operacion se considera nula.
            self.broker.vender(pos.motor, pos.simbolo, pos.cantidad, pos.precio_entrada)
            self.posiciones.remove(pos)
            if pos.id is not None:
                self.store.borrar_posicion(pos.id)
            self.store.incidente(
                "posicion_anulada",
                f"{pos.simbolo}: entrada {pos.precio_entrada} contra mercado "
                f"{precio} ({desvio * 100:.0f}% de desvio). Posicion anulada y "
                f"capital devuelto; no se registra como operacion.",
                "critico",
            )

    # ------------------------------------------------------------- decisiones

    def _registrar(self, motor: Motor, simbolo: str, accion: str, senal: Senal,
                   precio: Decimal, motivo: Optional[str] = None) -> None:
        self.store.guardar_decision(Decision(
            ts_ms=ahora_ms(), motor=motor, simbolo=simbolo, accion=accion,
            regla=senal.regla, motivo=motivo or senal.motivo, precio=precio,
            contexto=senal.contexto, version_config=self.version_config,
        ))

    # ----------------------------------------------------------------- ciclo

    def ciclo(self) -> None:
        try:
            precios = self.feed.precios(self.simbolos)
        except ErrorFeed as e:
            self.store.incidente("ciclo_sin_precios", str(e), "error")
            return

        if not self._validadas:
            self._validar_recuperadas(precios)
            self._validadas = True

        self._revisar_salidas(precios)
        self._buscar_entradas(precios)

        for cfg in self.motores:
            eq = self.equity(cfg.motor, precios)
            self.riesgo.revisar_drawdown(cfg.motor, eq)

        self.ciclos += 1
        self.ultimo_ciclo_ms = ahora_ms()

    # --------------------------------------------------------------- salidas

    def _revisar_salidas(self, precios: dict[str, Decimal]) -> None:
        for pos in list(self.posiciones):
            precio = precios.get(pos.simbolo)
            if precio is None:
                continue

            # El trailing stop sube con el precio, nunca baja.
            if pos.trailing_pct is not None:
                if precio > pos.max_precio_visto:
                    pos.max_precio_visto = precio
                    nuevo = precio * (Decimal("1") - pos.trailing_pct / Decimal("100"))
                    if nuevo > pos.stop_loss:
                        pos.stop_loss = nuevo
                        self.store.actualizar_posicion(pos)

            motivo: Optional[MotivoSalida] = None
            if precio <= pos.stop_loss:
                # Solo es "trailing" si el trailing llego a mover el stop de
                # verdad. Si nunca se movio, fue un stop loss normal, por mucho
                # que la posicion tuviera trailing configurado.
                movido = (pos.trailing_pct is not None
                          and pos.stop_inicial > 0
                          and pos.stop_loss > pos.stop_inicial)
                motivo = MotivoSalida.TRAILING_STOP if movido else MotivoSalida.STOP_LOSS
            elif precio >= pos.take_profit:
                motivo = MotivoSalida.TAKE_PROFIT
            elif pos.limite_tiempo_ms and ahora_ms() >= pos.limite_tiempo_ms:
                motivo = MotivoSalida.TIEMPO_AGOTADO

            if motivo is not None:
                self._cerrar(pos, precio, motivo)

    def _cerrar(self, pos: Posicion, precio: Decimal, motivo: MotivoSalida) -> None:
        try:
            precio_eje, comision = self.broker.vender(
                pos.motor, pos.simbolo, pos.cantidad, precio
            )
        except ErrorBroker as e:
            self.store.incidente("venta_rechazada", f"{pos.simbolo}: {e}", "error")
            return

        coste = pos.cantidad * pos.precio_entrada + pos.comision_entrada
        ingreso = pos.cantidad * precio_eje - comision
        pnl = ingreso - coste
        pnl_pct = (pnl / coste * Decimal("100")) if coste > 0 else Decimal("0")

        tp_pct = ((pos.take_profit - pos.precio_entrada) / pos.precio_entrada
                  * Decimal("100")) if pos.precio_entrada > 0 else Decimal("0")
        sl_pct = ((pos.precio_entrada - pos.stop_loss) / pos.precio_entrada
                  * Decimal("100")) if pos.precio_entrada > 0 else Decimal("0")

        velas = self._cache_velas.get(pos.simbolo, [])
        op = Operacion(
            motor=pos.motor, simbolo=pos.simbolo, cantidad=pos.cantidad,
            precio_entrada=pos.precio_entrada, precio_salida=precio_eje,
            entrada_ms=pos.entrada_ms, salida_ms=ahora_ms(), motivo_salida=motivo,
            regla=pos.regla, comisiones=pos.comision_entrada + comision,
            pnl=pnl, pnl_pct=pnl_pct,
            tp_esperado_pct=tp_pct.quantize(Decimal("0.01")),
            sl_esperado_pct=sl_pct.quantize(Decimal("0.01")),
            regimen=regimen(velas) if velas else "desconocido",
        )
        op.id = self.store.guardar_operacion(op)

        lec = leccion_de_operacion(op)
        self.ultima_leccion = {
            "simbolo": op.simbolo, "regla": op.regla, "pnl": str(op.pnl),
            "pnl_pct": f"{op.pnl_pct:+.2f}", "titulo": lec.titulo,
            "texto": lec.texto, "tipo": lec.tipo, "ts_ms": op.salida_ms,
        }
        self.store.set_estado("ultima_leccion", self.ultima_leccion)

        self.posiciones.remove(pos)
        if pos.id is not None:
            self.store.borrar_posicion(pos.id)

        self.store.guardar_decision(Decision(
            ts_ms=ahora_ms(), motor=pos.motor, simbolo=pos.simbolo, accion="salir",
            regla=pos.regla, motivo=f"{motivo.value}: {pnl_pct:+.2f}%",
            precio=precio_eje, contexto={"leccion": lec.titulo},
            version_config=self.version_config,
        ))

    # -------------------------------------------------------------- entradas

    def _buscar_entradas(self, precios: dict[str, Decimal]) -> None:
        for cfg in self.motores:
            if self.riesgo.esta_parado(cfg.motor):
                continue

            for simbolo in cfg.simbolos:
                precio = precios.get(simbolo)
                if precio is None:
                    continue
                if any(p.simbolo == simbolo and p.motor is cfg.motor
                       for p in self.posiciones):
                    continue

                velas = self._velas(simbolo)
                if not velas:
                    continue

                for est in cfg.estrategias:
                    senal = est.evaluar(simbolo, velas, precio)
                    if senal.accion != "entrar":
                        continue
                    if self._intentar_entrar(cfg.motor, simbolo, precio, senal, precios):
                        break   # una entrada por simbolo y ciclo

    def _velas(self, simbolo: str) -> list[Vela]:
        try:
            velas = self.feed.velas(simbolo, "1m", 200)
            if velas:
                self._cache_velas[simbolo] = velas
                self.store.guardar_velas(velas)
            return velas
        except ErrorFeed as e:
            self.store.incidente("velas_fallo", f"{simbolo}: {e}", "aviso")
            return self._cache_velas.get(simbolo, [])

    def _intentar_entrar(self, motor: Motor, simbolo: str, precio: Decimal,
                         senal: Senal, precios: dict[str, Decimal]) -> bool:
        saldo = self.broker.saldo(motor)
        importe = self.riesgo.importe_operacion(motor, saldo)
        veredicto = self.riesgo.puede_entrar(
            motor, importe, saldo, self.posiciones,
            self.valor_posiciones(motor, precios),
        )

        if not veredicto.permitido:
            self._registrar(motor, simbolo, "esperar", senal, precio,
                            motivo=f"vetado: {veredicto.motivo}")
            return False

        try:
            cantidad, precio_eje, comision = self.broker.comprar(
                motor, simbolo, importe, precio
            )
        except ErrorBroker as e:
            self.store.incidente("compra_rechazada", f"{simbolo}: {e}", "error")
            return False

        limite = (ahora_ms() + senal.minutos_max * 60_000
                  if senal.minutos_max else None)
        stop = precio_eje * (Decimal("1") - senal.sl_pct / Decimal("100"))
        pos = Posicion(
            id=0, motor=motor, simbolo=simbolo, cantidad=cantidad,
            precio_entrada=precio_eje, entrada_ms=ahora_ms(),
            stop_loss=stop,
            take_profit=precio_eje * (Decimal("1") + senal.tp_pct / Decimal("100")),
            stop_inicial=stop,
            trailing_pct=senal.trailing_pct, max_precio_visto=precio_eje,
            limite_tiempo_ms=limite, regla=senal.regla, comision_entrada=comision,
        )
        pos.id = self.store.guardar_posicion(pos)
        self.posiciones.append(pos)
        self._registrar(motor, simbolo, "entrar", senal, precio_eje)
        return True

    # ---------------------------------------------------------------- bucle

    def correr(self) -> None:
        self.store.incidente(
            "arranque",
            f"bot arrancado | feed={'REAL' if self.feed.es_real else 'sintetico'} "
            f"| broker={'REAL' if self.broker.es_real else 'papel'}",
            "aviso",
        )
        while not self._parar.is_set():
            inicio = time.time()
            try:
                self.ciclo()
            except Exception as e:  # noqa: BLE001 - el bucle no puede morir
                self.store.incidente(
                    "error_ciclo", f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                    "error",
                )
            espera = max(1.0, self.intervalo - (time.time() - inicio))
            self._parar.wait(espera)

    def detener(self) -> None:
        self._parar.set()
        self.store.incidente("parada", "bot detenido", "aviso")
