#!/bin/bash
# Script to start Swordfish development environment with proper X11 forwarding

# Parse command line arguments
NO_CACHE=""
FOREGROUND=""
NO_ENTRYPOINT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cache)
            NO_CACHE="--no-cache"
            echo "Building with --no-cache flag"
            shift
            ;;
        --foreground)
            FOREGROUND="true"
            echo "Running container in foreground"
            shift
            ;;
        --no-entry-point)
            NO_ENTRYPOINT="true"
            echo "Bypassing entrypoint"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--no-cache] [--foreground] [--no-entry-point]"
            exit 1
            ;;
    esac
done

# Set user info for docker compose
export HOST_UID=$(id -u)
export HOST_GID=$(id -g)
export HOST_USER=$(whoami)

# Use plain progress for detailed build output
export BUILDKIT_PROGRESS=plain

# Set cache directory as absolute path
export CACHE_DIR="$(realpath ../../cache/downloads)"
echo "Using cache directory: $CACHE_DIR"

# Test if proxy cache is reachable and set proxy variables
PROXY_HOST="192.168.80.20"
PROXY_PORT="3142"
PROXY_URL="http://${PROXY_HOST}:${PROXY_PORT}"

echo "Testing proxy cache at ${PROXY_URL}..."
if command -v nc >/dev/null 2>&1 && timeout 3 nc -z "${PROXY_HOST}" "${PROXY_PORT}" 2>/dev/null; then
    echo "✓ Proxy cache is reachable, using ${PROXY_URL} for HTTP only"
    export HTTP_PROXY="${PROXY_URL}"
elif command -v curl >/dev/null 2>&1 && timeout 3 curl -s --connect-timeout 2 "${PROXY_URL}" >/dev/null 2>&1; then
    echo "✓ Proxy cache is reachable (via curl), using ${PROXY_URL} for HTTP only"
    export HTTP_PROXY="${PROXY_URL}"
else
    echo "✗ Proxy cache not reachable, building without proxy"
    export HTTP_PROXY=""
fi

# Allow X11 connections from localhost
xhost +local:docker

# Build with verbose output first
sudo -E docker compose --progress=plain build --pull $NO_CACHE

# Start the development environment
if [[ "$FOREGROUND" == "true" ]]; then
    if [[ "$NO_ENTRYPOINT" == "true" ]]; then
        # Run in foreground with bypassed entrypoint (debug mode)
        sudo -E docker compose run --rm --entrypoint /bin/bash swordfish
    else
        # Run in foreground with normal entrypoint
        sudo -E docker compose run --rm swordfish
    fi
else
    # Run in background with normal entrypoint
    sudo -E docker compose up -d
    
    # Wait for the entrypoint to finish creating the user, then connect
    echo "Waiting for user setup to complete..."
    until sudo docker compose exec swordfish id "${HOST_USER}" >/dev/null 2>&1; do
        echo "User ${HOST_USER} not ready yet, waiting..."
        sleep 1
    done
    echo "User ${HOST_USER} is ready, connecting..."
    sudo docker compose exec --user "${HOST_USER}" -e PATH="/home/${HOST_USER}/.local/venv/bin:\$PATH" swordfish bash
    
    # Stop the container when the shell session ends
    echo "Shell session ended, stopping container..."
    sudo docker compose down
fi

# Clean up X11 permissions when done
xhost -local:docker
