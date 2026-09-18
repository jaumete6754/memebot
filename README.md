# Memebot — semana 1

Bot de trading en papel: **precios reales de Binance, dinero 100% virtual**.

No hay ni una clave de API en este proyecto, ni hace falta ninguna. Todos los
endpoints que usa son públicos.

## Instalación

En Termux (Android) o en cualquier Linux:

```bash
bash instalar.sh
python3 run.py
```

Después abre `http://localhost:8080` en el navegador.

Cero dependencias externas: solo la librería estándar de Python 3.10+. Por eso
se instala en segundos y no compila nada.

## Modos

```bash
python3 run.py               # precios reales de Binance, dinero virtual
python3 run.py --sintetico   # sin conexión, precios inventados (para probar)
python3 run.py --rapido      # ciclos de 5 s en vez de 60
```

## Qué hace

Dos motores con presupuestos **separados y estancos**:

| | Núcleo | Satélite |
|---|---|---|
| Capital | 110 USDT virtuales | 40 USDT virtuales |
| Pares | DOGE, SHIB, PEPE, BONK | FLOKI, WIF, MEME, NEIRO |
| Estrategias | cruce de medias, ruptura con volumen, exploración | ruptura con volumen, exploración agresiva |
| Drawdown máx. | 35% | 60% |

En cada ciclo: lee precios → revisa salidas (stop, objetivo, trailing, tiempo)
→ busca entradas → comprueba drawdown.

Las salidas se evalúan **antes** que las entradas: si el capital está al
límite, interesa liberar una posición perdedora antes que abrir otra.

## El modo exploración

Está activado por defecto (`"exploracion": true` en `config.json`). Entra
mucho, en muchos pares y con parámetros sorteados, equivocándose a menudo a
propósito. Con dinero virtual el error es gratis y genera datos variados.

**Lo que sí te da:** variedad de situaciones para comparar qué combinación de
objetivo y stop aguanta mejor en cada régimen de mercado.

**Lo que no te da:** una medida de rentabilidad. Entrar casi al azar produce
resultados dominados por el ruido. Además, las memecoins están muy
correlacionadas entre sí: ocho posiciones abiertas a la vez no son ocho
muestras independientes, son casi la misma apuesta repetida.

Por eso esas operaciones se marcan como `exploracion` y se contabilizan aparte.

## La capa de aprendizaje

Es la parte importante. Dos cosas distintas:

**1. Lección por operación.** Al cerrarse una posición se escribe qué esperaba
el bot, qué pasó y qué se deduce de la diferencia. Aparece arriba en el
dashboard. Ejemplo real de una ejecución de prueba:

> **Stop loss ejecutado** — Cayó hasta el stop del 2.00% en 45 s. Pérdida neta
> −3.18%. Perdiste 1.18 puntos MÁS que el stop nominal: esa diferencia son
> comisiones y slippage. Es el coste de operar, y se paga en cada ida y vuelta.

**2. Estadísticas acumuladas**, siempre con el número de muestras delante y su
margen de error. Por debajo de 30 operaciones el sistema dice explícitamente
que no se puede concluir nada, en vez de inventarse un hallazgo.

Esa es la regla del módulo: nunca presentar como conclusión algo que la muestra
no soporta.

## Estructura

```
memebot/
  types.py       dataclasses base (Decimal para el dinero, nunca float)
  store.py       journal SQLite: decisiones, operaciones, incidentes, posiciones
  feed.py        FeedBinance (real) y FeedSintetico (pruebas), misma interfaz
  broker.py      Broker ABC + BrokerPapel con fills pesimistas
  risk.py        gestor de riesgo con derecho de veto y kill-switch
  strategies.py  cruce de medias, ruptura con volumen, exploración
  learn.py       lecciones por operación y estadísticas honestas
  engine.py      el bucle principal
  dashboard.py   web de solo lectura, sin dependencias
run.py           arranque
config.json      toda la configuración
tests/           tests de las reglas de hierro
```

## Decisiones de diseño que no son negociables

**Un solo bot.** No existen «bot de pruebas» y «bot real»: existe un bot al que
se le inyecta un `Broker` distinto. Si algún día hiciera falta tocar otra cosa
para pasar a real, el paper trading estaría mintiendo.

**Fills pesimistas.** Slippage del 0,15% siempre en contra, más 0,1% de
comisión por lado. El paper trading es optimista por naturaleza porque no
modela la posición en la cola del libro; se compensa al alza. Hay un test que
verifica que comprar y vender al mismo precio **siempre** da pérdida.

**El satélite nunca se recarga del núcleo.** Está en el código y tiene tests.
Si los 40 se acaban, se acabaron.

**Las posiciones se persisten en disco.** Android mata procesos en segundo
plano; al reiniciar, el bot recupera exactamente dónde estaba. Un bot que
olvida sus posiciones al reiniciar deja stops sin vigilar.

**El dashboard es de solo lectura.** No existe ningún endpoint que abra o
cierre posiciones. Aunque alguien llegue a él, no puede mover dinero.

**Sin permiso de retirada, nunca.** `BrokerReal` está sin implementar a
propósito. Cuando llegue, leerá las claves de variables de entorno, y esa clave
debe tener retirada desactivada y whitelist de IP.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

16 tests que cubren separación de presupuestos, kill-switch por drawdown,
límites de exposición y nocional, pesimismo del broker, coherencia de las
lecciones y persistencia entre reinicios.

Cada incidente real que aparezca en producción debe añadir aquí un test que lo
reproduzca. Con el tiempo, esta suite es la memoria de todos los fallos que el
sistema ha visto.

## Aviso

Proyecto educativo. Nada de esto es asesoramiento financiero. El dinero es
virtual y así debe seguir hasta que se cumplan los criterios de salida
definidos en el plan: 30 días seguidos sin caídas, 100 operaciones o más,
batir a comprar y esperar, y al menos un incidente resuelto con su test.
