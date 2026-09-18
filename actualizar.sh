#!/bin/bash
# ===================================================================
#  Memebot - actualizar y arrancar, en un comando
#
#  Uso:   bash actualizar.sh
#
#  Que hace:
#    1. Busca el memebot*.zip mas reciente de tus Descargas
#    2. Hace copia de seguridad del codigo actual
#    3. Descomprime el zip encima
#    4. Ejecuta los tests
#         - pasan  -> arranca el bot
#         - fallan -> RESTAURA la version anterior y no arranca nada
#
#  No necesita GitHub, ni PC, ni conexion con nadie mas que Binance.
# ===================================================================

cd "$(dirname "$0")" || exit 1
PROY="$(pwd)"
RESPALDO="$PROY/.respaldo"

echo ""
echo "  MEMEBOT"
echo "  ======="
echo ""

# --- 0. si es un repositorio de git, traer cambios ----------------
ACTUALIZADO=0
if [ -d .git ] && command -v git >/dev/null 2>&1; then
    echo "  Buscando cambios en GitHub..."
    ANTES=$(git rev-parse HEAD 2>/dev/null)
    if git pull --ff-only 2>/dev/null; then
        DESPUES=$(git rev-parse HEAD 2>/dev/null)
        if [ "$ANTES" != "$DESPUES" ]; then
            echo "  Actualizado desde GitHub."
            git log --oneline "$ANTES..$DESPUES" 2>/dev/null | sed 's/^/    /'
            ACTUALIZADO=1
        else
            echo "  Ya estabas al dia."
        fi
    else
        echo "  No se pudo actualizar desde GitHub (sin red o con cambios locales)."
    fi
    echo ""
fi

# --- 1. buscar el zip mas reciente --------------------------------
ZIP=""
for DIR in "$HOME/storage/downloads" "$HOME/downloads" "/sdcard/Download" "$HOME"; do
    [ -d "$DIR" ] || continue
    CAND=$(ls -t "$DIR"/memebot*.zip 2>/dev/null | head -1)
    if [ -n "$CAND" ]; then ZIP="$CAND"; break; fi
done

if [ -z "$ZIP" ]; then
    if [ "$ACTUALIZADO" = "1" ]; then
        echo "  Comprobando el codigo nuevo..."
        if python -m unittest test_reglas >/dev/null 2>&1; then
            echo "  Tests OK"
        else
            echo ""
            echo "  LOS TESTS FALLAN tras actualizar desde GitHub."
            echo "  Volviendo a la version anterior..."
            git reset --hard "$ANTES" >/dev/null 2>&1
            echo "  Restaurado. El bot NO se ha arrancado."
            exit 1
        fi
    else
        echo "  Sin zip nuevo en Descargas. Arranco con el codigo actual."
    fi
    echo ""
else
    echo "  Zip encontrado:"
    echo "    $(basename "$ZIP")"
    echo "    descargado $(date -r "$ZIP" '+%d/%m %H:%M' 2>/dev/null || echo '')"
    echo ""

    # --- 2. copia de seguridad ------------------------------------
    rm -rf "$RESPALDO"
    mkdir -p "$RESPALDO"
    cp -f ./*.py ./*.json ./*.sh "$RESPALDO"/ 2>/dev/null
    echo "  Copia de seguridad hecha."

    # --- 3. descomprimir ------------------------------------------
    if ! unzip -o -q "$ZIP" -d "$PROY"; then
        echo "  ERROR al descomprimir. No se ha tocado nada."
        rm -rf "$RESPALDO"
        exit 1
    fi
    echo "  Codigo actualizado."

    # --- 4. los tests deciden -------------------------------------
    echo ""
    echo "  Comprobando..."
    if python -m unittest test_reglas >/dev/null 2>&1; then
        N=$(python -m unittest test_reglas -v 2>&1 | grep -c "... ok")
        echo "  $N tests OK"
        rm -rf "$RESPALDO"
    else
        echo ""
        echo "  *******************************************************"
        echo "  *  LOS TESTS FALLAN en la version nueva.              *"
        echo "  *  Restaurando la anterior...                         *"
        echo "  *******************************************************"
        cp -f "$RESPALDO"/* "$PROY"/ 2>/dev/null
        rm -rf "$RESPALDO"
        echo ""
        echo "  Restaurado. El bot NO se ha arrancado."
        echo "  Avisa de esto antes de seguir; para ver el detalle:"
        echo "      python -m unittest test_reglas -v"
        echo ""
        exit 1
    fi
fi

# --- 5. arrancar ---------------------------------------------------
echo ""
termux-wake-lock 2>/dev/null && echo "  Wake lock activado."
echo "  Panel: http://localhost:8080"
echo "  Ctrl+C para parar."
echo ""
exec python run.py "$@"
