#!/data/data/com.termux/files/usr/bin/bash
# Instalador para Termux (Android). Tambien funciona en Linux normal.
#
#   bash instalar.sh
#
# No instala ninguna dependencia externa: el proyecto solo usa la libreria
# estandar de Python. Por eso en el movil tarda segundos y no compila nada.

set -e

echo ""
echo "  Memebot - instalacion"
echo "  ---------------------"
echo ""

# --- Python -----------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "  Python no encontrado. Instalando..."
    if command -v pkg >/dev/null 2>&1; then
        pkg install -y python
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y python3
    else
        echo "  No se pudo instalar Python automaticamente. Instalalo a mano."
        exit 1
    fi
fi

VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python $VER detectado"
python3 - <<'EOF'
import sys
if sys.version_info < (3, 10):
    sys.exit("  Hace falta Python 3.10 o superior.")
EOF

# --- Comprobacion del codigo -------------------------------------------------
echo "  Comprobando el codigo..."
python3 -m unittest discover -s tests >/dev/null 2>&1 && \
    echo "  Tests OK" || echo "  AVISO: algun test ha fallado, revisalo antes de usarlo"

# --- Wake lock en Termux -----------------------------------------------------
if command -v termux-wake-lock >/dev/null 2>&1; then
    echo "  Activando wake lock (evita que Android mate el proceso)..."
    termux-wake-lock || true
    echo ""
    echo "  IMPORTANTE: ademas de esto, desactiva a mano la optimizacion de"
    echo "  bateria para Termux en los ajustes de Android. Si no, el sistema"
    echo "  acabara matando el bot igualmente."
fi

mkdir -p datos

echo ""
echo "  Listo. Para arrancar:"
echo ""
echo "      python3 run.py                # precios reales, dinero virtual"
echo "      python3 run.py --sintetico    # sin conexion, para probar"
echo "      python3 run.py --rapido       # ciclos de 5 s, para ver algo ya"
echo ""
echo "  Luego abre http://localhost:8080 en el navegador del movil."
echo ""
