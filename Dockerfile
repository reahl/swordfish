# Dockerfile for Swordfish development with GemStone/Smalltalk
# syntax=docker/dockerfile:1.6

FROM ubuntu:24.04

ARG GEMSTONE_VERSION=3.7.4.3
ARG http_proxy
ARG CACHE_DIR

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies including X11 support (use proxy for apt only)
RUN http_proxy=$http_proxy apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-tk \
    python3-dev \
    iputils-ping \
    git \
    build-essential \
    libffi-dev \
    libssl-dev \
    curl \
    wget \
    unzip \
    # Tools needed by GemStone installation scripts
    coreutils \
    sed \
    gawk \
    findutils \
    # System admin tools
    sudo \
    vim \
    # X11 and GUI support
    xvfb \
    x11-apps \
    libx11-dev \
    libxext-dev \
    libxrender-dev \
    libxtst6 \
    && rm -rf /var/lib/apt/lists/*

# Install gosu for user switching at runtime
RUN curl -L "https://github.com/tianon/gosu/releases/download/1.16/gosu-$(dpkg --print-architecture)" -o /usr/local/bin/gosu && \
    chmod +x /usr/local/bin/gosu

# Remove default ubuntu user and group to free up UID/GID 1000
RUN userdel -r ubuntu 2>/dev/null || true && \
    groupdel ubuntu 2>/dev/null || true

# Download GemStone installation scripts from parseltongue repository
RUN mkdir -p /opt/dev/gemstone && \
    curl -L https://raw.githubusercontent.com/reahl/parseltongue/master/gemstone/answersForInstallgs.sh -o /opt/dev/gemstone/answersForInstallgs.sh && \
    curl -L https://raw.githubusercontent.com/reahl/parseltongue/master/gemstone/defineGemStoneEnvironment.sh -o /opt/dev/gemstone/defineGemStoneEnvironment.sh && \
    curl -L https://raw.githubusercontent.com/reahl/parseltongue/master/gemstone/gemShell.sh -o /opt/dev/gemstone/gemShell.sh && \
    curl -L https://raw.githubusercontent.com/reahl/parseltongue/master/gemstone/installGemStone.sh -o /opt/dev/gemstone/installGemStone.sh && \
    chmod +x /opt/dev/gemstone/*.sh

# Create gemstone user for running GemStone  
RUN useradd -r -m -s /bin/bash gemstone

# Install GemStone as root with gemstone user settings (with cache mount)
RUN --mount=type=cache,target=/home/gemstone/testdownloads,id=gemstone-downloads \
    cd /opt/dev/gemstone && \
    export DEV_HOME=/home/gemstone && \
    export DEV_USER=gemstone && \
    ./installGemStone.sh ${GEMSTONE_VERSION}

# Create entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Set up workspace directory
RUN mkdir -p /workspace

# Set up X11 forwarding for GUI
ENV DISPLAY=:0

WORKDIR /workspace

# Default command
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/bin/bash"]
