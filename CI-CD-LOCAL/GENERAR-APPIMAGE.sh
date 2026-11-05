#!/usr/bin/env bash
# ============================================================================
#  GENERAR-APPIMAGE.sh — build LOCAL de Swap Resizer
#  Produce OUT/SwapResizer-x86_64.AppImage (PyInstaller onefile + AppDir).
#  El mismo script corre .github/workflows/release.yml en la nube.
#  Requisitos: python3 + pip + curl (appimagetool se descarga solo).
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

# Si hay .venv usarla; si no, el python3 del PATH (= setup-python en CI)
PYBIN="python3"
if [ -x .venv/bin/python ]; then
    PYBIN=".venv/bin/python"
fi

echo "==> Dependencias python"
"$PYBIN" -m pip install -q --upgrade pip
"$PYBIN" -m pip install -q -r requirements.txt pyinstaller

echo "==> PyInstaller (onefile, ventana)"
# apply_swap.sh va embebido: en runtime __file__ apunta al _MEIPASS y
# APPLY_SCRIPT (SCRIPT_DIR/apply_swap.sh) resuelve dentro del bundle.
"$PYBIN" -m PyInstaller --noconfirm --clean \
    --onefile --windowed \
    --name SwapResizer \
    --add-data "apply_swap.sh:." \
    swap_resizer.py

echo "==> AppDir"
APPDIR="OUT/AppDir"
rm -rf OUT
mkdir -p "$APPDIR/usr/bin"
cp dist/SwapResizer "$APPDIR/usr/bin/"

cat > "$APPDIR/swap-resizer.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Swap Resizer
Comment=Monitoriza y redimensiona el swapfile
Exec=SwapResizer
Icon=swap-resizer
Categories=System;Utility;
Terminal=false
EOF

cp readme/readme.png "$APPDIR/swap-resizer.png"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/SwapResizer" "$@"
EOF
chmod +x "$APPDIR/AppRun"

echo "==> appimagetool"
CACHEDIR="${XDG_CACHE_HOME:-$HOME/.cache}/swap-resizer-build"
mkdir -p "$CACHEDIR"
TOOL="$CACHEDIR/appimagetool-x86_64.AppImage"
if [ ! -f "$TOOL" ]; then
    curl -fSL -o "$TOOL" \
        "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
fi
chmod +x "$TOOL"

echo "==> AppImage"
# --appimage-extract-and-run: en CI no hay FUSE
ARCH=x86_64 "$TOOL" --appimage-extract-and-run \
    "$APPDIR" "OUT/SwapResizer-x86_64.AppImage"

echo "OK: OUT/SwapResizer-x86_64.AppImage"
