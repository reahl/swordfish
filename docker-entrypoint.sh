#!/bin/bash
set -e

# Handle signals properly for clean container shutdown
trap 'echo "Received signal, shutting down..."; exit 0' SIGTERM SIGINT

# Get user info from environment variables (set by docker-compose)
USER_ID=${USER_ID:-1000}
GROUP_ID=${GROUP_ID:-1000}
USERNAME=${USERNAME:-developer}

# Create group if it doesn't exist
if ! getent group "$USERNAME" >/dev/null 2>&1; then
    groupadd -g "$GROUP_ID" "$USERNAME"
fi

# Create user if it doesn't exist
if ! getent passwd "$USERNAME" >/dev/null 2>&1; then
    useradd -m -u "$USER_ID" -g "$GROUP_ID" -s /bin/bash "$USERNAME"
    echo "$USERNAME:developer" | chpasswd
    usermod -aG sudo "$USERNAME"
    echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
fi

# Set up GemStone environment for the user
USER_HOME=$(getent passwd "$USERNAME" | cut -d: -f6)
if [ -f /opt/dev/defineGemStoneEnvironment.sh ]; then
    if ! grep -q "defineGemStoneEnvironment.sh" "$USER_HOME/.bashrc" 2>/dev/null; then
        echo "source /opt/dev/defineGemStoneEnvironment.sh \$GEMSTONE_VERSION" >> "$USER_HOME/.bashrc"
        echo "export GEMSTONE_VERSION=3.7.4.3" >> "$USER_HOME/.bashrc"
    fi
fi

# Install Python development tools for the user in a virtual environment
if [ ! -f "$USER_HOME/.dev_tools_installed" ]; then
    # Ensure the user's home directory exists and has proper permissions
    mkdir -p "$USER_HOME"
    chown "$USERNAME:$USERNAME" "$USER_HOME"
    
    # Create virtual environment for development tools
    gosu "$USERNAME" python3 -m venv "$USER_HOME/.local/venv"
    gosu "$USERNAME" "$USER_HOME/.local/venv/bin/pip" install black isort pytest
    
    # Add venv to PATH in .bashrc so tools are available
    if ! grep -q ".local/venv/bin" "$USER_HOME/.bashrc" 2>/dev/null; then
        echo "export PATH=\"\$HOME/.local/venv/bin:\$PATH\"" >> "$USER_HOME/.bashrc"
    fi
    
    touch "$USER_HOME/.dev_tools_installed"
fi

# Change ownership of workspace to the user
chown -R "$USERNAME:$USERNAME" /workspace

# Set up X11 socket permissions for secure GUI access
if [ -S /tmp/.X11-unix/X0 ]; then
    chmod 755 /tmp/.X11-unix/X0 2>/dev/null || true
fi

# Ensure X11 auth file has correct ownership if it exists
if [ -f "$USER_HOME/.Xauthority" ]; then
    chown "$USERNAME:$USERNAME" "$USER_HOME/.Xauthority" 2>/dev/null || true
fi

# Execute the command as the user
exec gosu "$USERNAME" "$@"