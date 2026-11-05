#!/bin/bash
# Redimensiona /swapfile al tamaño indicado en GB.
# Uso: pkexec bash apply_swap.sh <SIZE_GB>
set -e

SIZE_GB="$1"
SWAPFILE="/swapfile"

if ! [[ "$SIZE_GB" =~ ^[0-9]+$ ]] || [ "$SIZE_GB" -lt 1 ]; then
    echo "Tamaño inválido: $SIZE_GB" >&2
    exit 1
fi

echo "Desactivando swap..."
swapoff "$SWAPFILE"

echo "Creando archivo de ${SIZE_GB}G..."
if ! fallocate -l "${SIZE_GB}G" "$SWAPFILE"; then
    echo "fallocate falló, usando dd..."
    dd if=/dev/zero of="$SWAPFILE" bs=1M count=$((SIZE_GB * 1024)) status=none
fi

chmod 600 "$SWAPFILE"

echo "Formateando como swap..."
mkswap "$SWAPFILE"

echo "Activando swap..."
swapon "$SWAPFILE"

echo "OK: swap de ${SIZE_GB}G activo."
