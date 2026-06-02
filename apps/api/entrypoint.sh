#!/bin/bash
set -e

echo "=== WGS Cockpit API Starting ==="

# ── GPU Detection ──────────────────────────────────────────────
GPU_AVAILABLE=false
GPU_INFO="none"

if command -v nvidia-smi &>/dev/null; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1 || echo "nvidia-smi failed")
    if [ -n "$GPU_INFO" ] && [ "$GPU_INFO" != "nvidia-smi failed" ]; then
        GPU_AVAILABLE=true
        echo "[gpu] Detected: $GPU_INFO"
    fi
fi

if [ "$GPU_AVAILABLE" = "false" ]; then
    # Check for /dev/nvidia* (Docker Desktop/WSL2 passthrough)
    if ls /dev/nvidia* &>/dev/null 2>&1; then
        GPU_AVAILABLE=true
        GPU_INFO="NVIDIA GPU (via /dev/nvidia* passthrough)"
        echo "[gpu] Detected: $GPU_INFO"
    fi
fi

if [ "$GPU_AVAILABLE" = "false" ]; then
    echo "[gpu] No GPU detected — DeepVariant will run in CPU mode"
fi

export WGS_GPU_AVAILABLE="$GPU_AVAILABLE"
export WGS_GPU_INFO="$GPU_INFO"

# ── SIMD Detection ─────────────────────────────────────────────
SIMD="unknown"
if [ -f /proc/cpuinfo ]; then
    if grep -q avx512 /proc/cpuinfo 2>/dev/null; then
        SIMD="avx512"
    elif grep -q avx2 /proc/cpuinfo 2>/dev/null; then
        SIMD="avx2"
    elif grep -q sse4_2 /proc/cpuinfo 2>/dev/null; then
        SIMD="sse42"
    elif grep -q sse4_1 /proc/cpuinfo 2>/dev/null; then
        SIMD="sse41"
    fi
fi
export WGS_SIMD_LEVEL="$SIMD"
echo "[cpu] SIMD level: $SIMD"

# ── Tool Versions ──────────────────────────────────────────────
echo "[tools] $(samtools --version 2>/dev/null | head -1 || echo 'samtools: missing')"
echo "[tools] $(bcftools --version 2>/dev/null | head -1 || echo 'bcftools: missing')"
echo "[tools] $(bwa-mem2 version 2>&1 | head -1 || echo 'bwa-mem2: missing')"
echo "[tools] $(mosdepth --version 2>/dev/null || echo 'mosdepth: missing')"

echo "=== Starting API Server ==="

# Inject SSH public key from env
if [ -n "$SSH_AUTHORIZED_KEYS" ]; then
    echo "$SSH_AUTHORIZED_KEYS" > /home/wgs/.ssh/authorized_keys
    chown -R wgs:wgs /home/wgs/.ssh
    chmod 700 /home/wgs/.ssh
    chmod 600 /home/wgs/.ssh/authorized_keys
fi

# Start SSH daemon
mkdir -p /run/sshd
/usr/sbin/sshd 2>/dev/null || true

# Start API server
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
