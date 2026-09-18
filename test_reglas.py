"""Tests de las reglas de hierro.

Estos tests existen para que las reglas no se puedan romper por accidente en un
refactor futuro. Cada vez que aparezca un incidente real en produccion, se
anade aqui un test que lo reproduce: esta suite acaba siendo la memoria de
todos los fallos que el sistema ha visto.

    python3 -m unittest test_reglas -v
"""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from broker import BrokerPapel, ErrorBroker
from learn import leccion_de_operacion     
from risk import GestorRiesgo, LimitesMotor
from store import Store                    
from modelo import Motor, MotivoSalida, Operacion     # noqa: E402


def _riesgo(nucleo="110", satelite="40") -> GestorRiesgo:
    return GestorRiesgo(limites={
        Motor.NUCLEO: LimitesMotor(capital_inicial=Decimal(nucleo)),
        Motor.SATELITE: LimitesMotor(capital_inicial=Decimal(satelite),
                                     max_posiciones=3),
    })


class TestSeparacionPresupuestos(unittest.TestCase):
    """REGLA DE HIERRO: el satelite nunca se recarga desde el nucleo."""

    def test_satelite_no_puede_gastar_mas_que_su_saldo(self):
        r = _riesgo()
        # El nucleo tiene 110 disponibles, pero al satelite le quedan 3.
        v = r.puede_entrar(Motor.SATELITE, Decimal("10"), Decimal("3"), [], Decimal("0"))
        self.assertFalse(v.permitido)
        self.assertIn("saldo insuficiente", v.motivo)

    def test_satelite_agotado_no_puede_operar(self):
        r = _riesgo()
        v = r.puede_entrar(Motor.SATELITE, Decimal("8"), Decimal("0"), [], Decimal("0"))
        self.assertFalse(v.permitido)

    def test_broker_no_permite_gastar_de_otro_motor(self):
        b = BrokerPapel({Motor.NUCLEO: Decimal("110"), Motor.SATELITE: Decimal("2")})
        with self.assertRaises(ErrorBroker):
            b.comprar(Motor.SATELITE, "PEPEUSDT", Decimal("10"), Decimal("1"))
        # El saldo del nucleo no se ha tocado.
        self.assertEqual(b.saldo(Motor.NUCLEO), Decimal("110"))


class TestKillSwitch(unittest.TestCase):
    def test_drawdown_detiene_el_motor(self):
        r = _riesgo(nucleo="100")
        self.assertIsNone(r.revisar_drawdown(Motor.NUCLEO, Decimal("80")))   # -20%
        self.assertFalse(r.esta_parado(Motor.NUCLEO))
        motivo = r.revisar_drawdown(Motor.NUCLEO, Decimal("60"))             # -40%
        self.assertIsNotNone(motivo)
        self.assertTrue(r.esta_parado(Motor.NUCLEO))

    def test_motor_parado_rechaza_entradas(self):
        r = _riesgo()
        r.parar(Motor.NUCLEO, "prueba")
        v = r.puede_entrar(Motor.NUCLEO, Decimal("10"), Decimal("100"), [], Decimal("0"))
        self.assertFalse(v.permitido)

    def test_parar_un_motor_no_afecta_al_otro(self):
        r = _riesgo()
        r.parar(Motor.NUCLEO, "prueba")
        self.assertFalse(r.esta_parado(Motor.SATELITE))


class TestLimites(unittest.TestCase):
    def test_minimo_nocional(self):
        r = _riesgo()
        v = r.puede_entrar(Motor.NUCLEO, Decimal("2"), Decimal("100"), [], Decimal("0"))
        self.assertFalse(v.permitido)
        self.assertIn("minimo nocional", v.motivo)

    def test_exposicion_maxima(self):
        r = _riesgo(nucleo="100")
        # 85 ya invertidos + 10 nuevos sobre un equity de 100 supera el 80%.
        v = r.puede_entrar(Motor.NUCLEO, Decimal("10"), Decimal("15"),
                           [], Decimal("85"))
        self.assertFalse(v.permitido)
        self.assertIn("exposicion", v.motivo)


class TestBrokerPesimista(unittest.TestCase):
    """El slippage simulado SIEMPRE va en contra. Nunca a favor."""

    def setUp(self):
        self.b = BrokerPapel(
            {Motor.NUCLEO: Decimal("100")},
            comision_pct=Decimal("0.1"), slippage_pct=Decimal("0.15"),
        )

    def test_compra_mas_caro_que_el_precio(self):
        _, precio_eje, _ = self.b.comprar(
            Motor.NUCLEO, "PEPEUSDT", Decimal("10"), Decimal("100")
        )
        self.assertGreater(precio_eje, Decimal("100"))

    def test_venta_mas_barata_que_el_precio(self):
        precio_eje, _ = self.b.vender(
            Motor.NUCLEO, "PEPEUSDT", Decimal("1"), Decimal("100")
        )
        self.assertLess(precio_eje, Decimal("100"))

    def test_ida_y_vuelta_sin_movimiento_pierde_dinero(self):
        """Comprar y vender al mismo precio DEBE dar perdida. Es el coste real."""
        inicial = self.b.saldo(Motor.NUCLEO)
        cant, _, _ = self.b.comprar(Motor.NUCLEO, "X", Decimal("10"), Decimal("100"))
        self.b.vender(Motor.NUCLEO, "X", cant, Decimal("100"))
        self.assertLess(self.b.saldo(Motor.NUCLEO), inicial)


class TestLecciones(unittest.TestCase):
    """Una leccion nunca debe contradecir el resultado que describe."""

    @staticmethod
    def _op(motivo, pnl, pnl_pct, sl=Decimal("3")) -> Operacion:
        return Operacion(
            motor=Motor.NUCLEO, simbolo="PEPEUSDT", cantidad=Decimal("1"),
            precio_entrada=Decimal("100"), precio_salida=Decimal("98"),
            entrada_ms=0, salida_ms=60_000, motivo_salida=motivo,
            regla="cruce_medias", comisiones=Decimal("0.02"),
            pnl=pnl, pnl_pct=pnl_pct, tp_esperado_pct=Decimal("6"),
            sl_esperado_pct=sl, regimen="bajista_volatil",
        )

    def test_trailing_con_perdida_no_dice_que_protegio_ganancia(self):
        lec = leccion_de_operacion(
            self._op(MotivoSalida.TRAILING_STOP, Decimal("-0.5"), Decimal("-2.86"))
        )
        self.assertEqual(lec.tipo, "malo")
        self.assertNotIn("protegio la ganancia", lec.texto)

    def test_trailing_con_ganancia_es_bueno(self):
        lec = leccion_de_operacion(
            self._op(MotivoSalida.TRAILING_STOP, Decimal("0.5"), Decimal("2.5"))
        )
        self.assertEqual(lec.tipo, "bueno")

    def test_stop_explica_el_hueco_por_costes(self):
        lec = leccion_de_operacion(
            self._op(MotivoSalida.STOP_LOSS, Decimal("-0.6"), Decimal("-3.18"),
                     sl=Decimal("2"))
        )
        self.assertIn("comisiones y slippage", lec.texto)


class TestAprendizajeHonesto(unittest.TestCase):
    def test_muestra_pequena_no_concluye(self):
        from learn import Aprendizaje
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "t.db")
            for i in range(5):
                store.guardar_operacion(TestLecciones._op(
                    MotivoSalida.TAKE_PROFIT, Decimal("1"), Decimal("5")))
            concl = Aprendizaje(store).informe()["conclusiones"]
            self.assertEqual(len(concl), 1)
            self.assertEqual(concl[0]["nivel"], "insuficiente")
            store.cerrar()


class TestPersistencia(unittest.TestCase):
    def test_posiciones_sobreviven_al_reinicio(self):
        from modelo import Posicion
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "t.db"
            s1 = Store(ruta)
            p = Posicion(
                id=0, motor=Motor.SATELITE, simbolo="WIFUSDT",
                cantidad=Decimal("5"), precio_entrada=Decimal("2"),
                entrada_ms=1000, stop_loss=Decimal("1.9"),
                take_profit=Decimal("2.2"), stop_inicial=Decimal("1.9"),
                max_precio_visto=Decimal("2"), regla="exploracion",
            )
            s1.guardar_posicion(p)
            s1.cerrar()

            s2 = Store(ruta)          # simula el reinicio del proceso
            recuperadas = s2.posiciones_abiertas()
            self.assertEqual(len(recuperadas), 1)
            self.assertEqual(recuperadas[0].simbolo, "WIFUSDT")
            self.assertEqual(recuperadas[0].motor, Motor.SATELITE)
            s2.cerrar()


if __name__ == "__main__":
    unittest.main()
