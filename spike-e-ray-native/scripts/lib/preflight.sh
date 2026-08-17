#!/usr/bin/env bash
# preflight.sh — report which prerequisites are present or missing.
#
# Exits 0 with a summary.  Steps 3-7 check these before doing work.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# preflight.sh lives in scripts/lib/, env.sh is at spike-e-ray-native/env.sh
source "${SCRIPT_DIR}/../../env.sh"

# Columns: command label, check_name, required_for
# required_for: empty = devcontainer-only; "gpu-steps" = 3-7
declare -A PRECHECK
PRECHECK=(
    ["python"]="python"
    ["ray"]="ray (host)"
    ["serve"]="serve (CLI)"
    ["podman"]="podman (container runtime)"
    ["nvidia-smi"]="nvidia-smi (GPU)"
    ["nvidia-ctk"]="nvidia-ctk (NVIDIA toolkit)"
    ["docker"]="docker (coexistence check)"
)

REQUIRED_FOR_GPU_STEPS=(
    "python" "ray" "serve" "podman" "nvidia-smi"
)

echo "============================================================"
echo "Spike E — Preflight Check"
echo "============================================================"
echo ""

declare -A FOUND
MISSING=0
HAS_GPU=0

for cmd in "${!PRECHECK[@]}"; do
    if command -v "$cmd" &>/dev/null; then
        version=""
        case "$cmd" in
            python)     version="v$(python --version 2>&1 || echo "?")" ;;
            ray)        version="$(ray --version 2>&1 || echo "?")" ;;
            serve)      version="$(serve --version 2>&1 || echo "?")" ;;
            podman)     version="$(podman version 2>&1 | head -1 || echo "?")" ;;
            nvidia-smi) version="$(nvidia-smi --query-gpu=name --format=csv 2>/dev/null | tail -1 || echo "?")"
                        if [[ "$version" != "?" ]]; then HAS_GPU=1; fi ;;
            nvidia-ctk) version="$(nvidia-ctk --version 2>&1 || echo "?")" ;;
            docker)     version="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?')" ;;
        esac
        printf "  [OK]   %-15s  %s\n" "${PRECHECK[$cmd]}" "$version"
        FOUND["$cmd"]=1
    else
        printf "  [MISS] %-15s  not found\n" "${PRECHECK[$cmd]}"
        FOUND["$cmd"]=0
        MISSING=$((MISSING + 1))
    fi
done

echo ""
echo "============================================================"

if [[ "$HAS_GPU" -eq 0 ]]; then
    echo "GPU: not detected"
    echo "Steps 3-7 require a GPU and will refuse to run."
else
    echo "GPU: detected"
fi

echo ""

# Check requests Python package
if python -c "import requests" 2>/dev/null; then
    REQ_VER=$(python -c "import requests; print(requests.__version__)" 2>/dev/null || echo "?")
    printf "  [OK]   %-15s  %s\n" "requests (Python)" "$REQ_VER"
    FOUND["requests"]=1
else
    printf "  [MISS] %-15s  not installed (pip install requests)\n" "requests (Python)"
    FOUND["requests"]=0
    MISSING=$((MISSING + 1))
fi

echo ""

# Summary
echo "Prerequisites: $(echo "${!FOUND[@]}" | tr ' ' '\n' | wc -l) checked, $MISSING missing."

if [[ "$HAS_GPU" -eq 0 ]]; then
    echo ""
    echo "Steps 1-2 (no GPU needed) are runnable in this devcontainer."
    echo "Steps 3-7 require the DGX host (or another GPU box with"
    echo "podman, nvidia-smi, and a running Ray cluster)."
    echo "See plans/spike-E-implementation.md §6.1 assumption 8."
    exit 0
fi

if [[ "$MISSING" -gt 0 ]]; then
    echo ""
    echo "Steps 3-7 need: python, ray, serve, podman, nvidia-smi."
    echo "Missing: $(for k in "${!FOUND[@]}"; do [[ "${FOUND[$k]}" -eq 0 ]] && printf "%s " "$k"; done)"
    echo "Proceed with caution."
else
    echo "All prerequisites for steps 3-7 are present."
fi

exit 0
