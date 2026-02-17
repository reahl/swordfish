#!/bin/bash
set -e

# Handle signals properly for clean container shutdown
trap 'echo "Received signal, shutting down..."; exit 0' SIGTERM SIGINT

# Get user info from environment variables (set by docker-compose)
USER_ID=${USER_ID:-1000}
GROUP_ID=${GROUP_ID:-1000}
USERNAME=${USERNAME:-developer}
ENABLE_SSHD=${ENABLE_SSHD:-false}
SSH_PORT=${SSH_PORT:-2222}
SSH_BIND_ADDRESS=${SSH_BIND_ADDRESS:-127.0.0.1}
SSH_AUTHORIZED_KEY=${SSH_AUTHORIZED_KEY:-}

# Create group if it doesn't exist
if ! getent group "$USERNAME" >/dev/null 2>&1; then
    groupadd -g "$GROUP_ID" "$USERNAME"
fi

# Create user if it doesn't exist
if ! getent passwd "$USERNAME" >/dev/null 2>&1; then
    useradd -m -u "$USER_ID" -g "$GROUP_ID" -s /bin/bash "$USERNAME"
    echo "$USERNAME:developer" | chpasswd
    usermod -aG sudo "$USERNAME"
    # Add development user to gemstone group for GemStone file access
    usermod -aG gemstone "$USERNAME"
    echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
fi

# Ensure the user's home directory exists and has proper permissions first
USER_HOME=$(getent passwd "$USERNAME" | cut -d: -f6)
mkdir -p "$USER_HOME"
chown "$USERNAME:$USERNAME" "$USER_HOME"

# Set up GemStone environment for the user
if [ -f /opt/dev/gemstone/defineGemStoneEnvironment.sh ]; then
    if [ ! -f "$USER_HOME/.gemstone_setup_done" ]; then
        echo "Setting up GemStone environment for $USERNAME"
        gosu "$USERNAME" /opt/dev/gemstone/defineGemStoneEnvironment.sh 3.7.4.3
        # Also add the GemStone environment directly to the user's profile for immediate access
        if ! grep -q "GEMSHELL" "$USER_HOME/.profile" 2>/dev/null; then
            echo "" >> "$USER_HOME/.profile"
            echo "# GemStone Environment" >> "$USER_HOME/.profile"
            echo "echo GEMSHELL: /opt/dev/gemstone/gemShell.sh" >> "$USER_HOME/.profile"
            echo "VERSION=3.7.4.3" >> "$USER_HOME/.profile"
            echo ". /opt/dev/gemstone/gemShell.sh 3.7.4.3" >> "$USER_HOME/.profile"
        fi
        touch "$USER_HOME/.gemstone_setup_done"
    fi
fi

# Install Python development tools for the user in a virtual environment
if [ ! -f "$USER_HOME/.dev_tools_installed" ]; then
    
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

# Set up GemStone configuration and environment for gemstone user
if [ -f /opt/gemstone/GemStone*/bin/initial.config ]; then
    GEMSTONE_DIR=$(ls -d /opt/gemstone/GemStone* | head -1)
    if [ ! -f "$GEMSTONE_DIR/data/system.conf" ]; then
        echo "Setting up GemStone system configuration..."
        mkdir -p "$GEMSTONE_DIR/data"
        cp "$GEMSTONE_DIR/bin/initial.config" "$GEMSTONE_DIR/data/system.conf"
        chown -R gemstone:gemstone "$GEMSTONE_DIR/data"
    fi
    
    # Set up GemStone environment for gemstone user
    GEMSTONE_USER_HOME="/home/gemstone"
    if [ -f /opt/dev/gemstone/defineGemStoneEnvironment.sh ] && [ ! -f "$GEMSTONE_USER_HOME/.gemstone_setup_done" ]; then
        echo "Setting up GemStone environment for gemstone user..."
        gosu gemstone /opt/dev/gemstone/defineGemStoneEnvironment.sh 3.7.4.3
        # Note: .profile already sources .bashrc, so no circular reference needed
        touch "$GEMSTONE_USER_HOME/.gemstone_setup_done"
    fi
fi

# Set up X11 socket permissions for secure GUI access
if [ -S /tmp/.X11-unix/X0 ]; then
    chmod 755 /tmp/.X11-unix/X0 2>/dev/null || true
fi

# Ensure X11 auth file has correct ownership if it exists
if [ -f "$USER_HOME/.Xauthority" ]; then
    chown "$USERNAME:$USERNAME" "$USER_HOME/.Xauthority" 2>/dev/null || true
fi

if [ "$ENABLE_SSHD" = "true" ]; then
    mkdir -p /run/sshd
    ssh-keygen -A >/dev/null
    USER_SSH_DIR="$USER_HOME/.ssh"
    AUTHORIZED_KEYS_FILE="$USER_SSH_DIR/authorized_keys"
    mkdir -p "$USER_SSH_DIR"
    touch "$AUTHORIZED_KEYS_FILE"
    if [ -n "$SSH_AUTHORIZED_KEY" ]; then
        printf '%s\n' "$SSH_AUTHORIZED_KEY" >> "$AUTHORIZED_KEYS_FILE"
    fi
    sort -u "$AUTHORIZED_KEYS_FILE" -o "$AUTHORIZED_KEYS_FILE"
    chmod 700 "$USER_SSH_DIR"
    chmod 600 "$AUTHORIZED_KEYS_FILE"
    chown -R "$USERNAME:$USERNAME" "$USER_SSH_DIR"
    mkdir -p /etc/ssh/sshd_config.d
    cat > /etc/ssh/sshd_config.d/swordfish.conf <<EOF
Port $SSH_PORT
ListenAddress $SSH_BIND_ADDRESS
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
UsePAM no
PermitRootLogin no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
AllowUsers $USERNAME
AllowTcpForwarding no
X11Forwarding no
PermitTunnel no
GatewayPorts no
PrintMotd no
EOF
    /usr/sbin/sshd
    echo "SSH server is listening on ${SSH_BIND_ADDRESS}:${SSH_PORT}"
fi

# Execute the command as the user
exec gosu "$USERNAME" "$@"
