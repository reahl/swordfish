# Swordfish

A classic Smalltalk IDE for GemStone/Smalltalk developed by Reahl Software Services.

## Overview

Swordfish is a Python-based IDE that provides a classic Smalltalk development experience for GemStone/Smalltalk. It features class/method browsing, method editing, debugging capabilities with stepping functionality, and an object inspector.

Swordfish also ships with a built-in **MCP (Model Context Protocol) server**. The MCP gives AI agents — such as Claude — two complementary capabilities: full programmatic access to the GemStone Smalltalk codebase (read source, compile methods, run tests, refactor, trace callers, …) *and* direct control of the live IDE itself (navigate to a class, open a method in the editor, open the debugger, narrow the list of senders in the Find dialog, compose UML diagrams, and more). This means you can literally ask your AI assistant to show you something in the IDE, or have it step through a failing test with the debugger open in front of you.

This project was developed as an experiment in AI-assisted programming, with significant portions (including this README and other metadata) generated through collaboration between human developers and AI, followed by developer refinement and refactoring.

## Features

- **Class and method browsing**
- **Method editing**
- **Debugging with step execution**
- **Object inspection**
- **UML class and object diagrams** — build and explore class structure diagrams and live object graphs interactively; diagrams open as tabs alongside the browser and can be driven manually or by an AI agent via MCP
- **Embedded MCP server** — lets AI agents interact with both the codebase and the live IDE

## Technical Details

Swordfish is built with:
- Python
- Tcl/Tk for the GUI interface (implemented without prior knowledge of the toolkit)
- Parseltongue (reahl-parseltongue) - library that enables calling GemStone/Smalltalk methods from Python

## IDE

This section covers using Swordfish as a GUI IDE via the `swordfish` command.

### Installation

For Docker-based development of both IDE and MCP, see `How to Develop (Docker)` at the end of this README.

### From PyPI (Recommended)

```bash
# Create a virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install from PyPI
pip install reahl-swordfish
```

### From Source

```bash
# Clone the repository
git clone https://github.com/reahl/swordfish.git
cd swordfish

# Set up a virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e .
```

### Run the IDE

```bash
# After installation, run directly from command line
swordfish

# Or if installed from source
python -m swordfish
```

## MCP

Swordfish includes MCP modes on the same `swordfish` executable.

### Install

```bash
pip install reahl-swordfish
```

### Run the server

```bash
swordfish --headless-mcp
```

### Attach Claude to a running IDE/MCP process

To let Claude connect to an MCP server hosted inside an already-running IDE
process, start the GUI (it starts the embedded MCP server automatically):

```bash
swordfish --mcp-host 0.0.0.0 --mcp-port 9177 --mcp-http-path /mcp
```

Then configure Claude outside the container to use that URL:

```bash
claude mcp remove -s project swordfish 2>/dev/null || true
claude mcp add -s project --transport http swordfish http://127.0.0.1:9177/mcp
claude mcp list
```

`stdio` mode cannot attach to an already-running process. Use the `MCP` menu
in the GUI to start/stop the embedded server and edit runtime policy and
network settings.

### Add MCP to Claude Code and Codex (Docker-over-SSH)

For Docker and SSH setup details, see `How to Develop (Docker)` at the end of
this README.

Start the development container with SSH enabled:

```bash
./docker-start.sh --enable-ssh --ssh-pubkey-file ~/.ssh/id_ed25519.pub --foreground
```

Then configure MCP clients to launch `swordfish --headless-mcp` through
`docker-run-over-ssh.sh`:

```bash
PROJECT_DIR="$(pwd)"

# Claude Code
claude mcp remove -s project swordfish 2>/dev/null || true
claude mcp add -s project swordfish -- "$PROJECT_DIR/docker-run-over-ssh.sh" swordfish --headless-mcp --allow-compile --allow-tracing
claude mcp list

# Codex
codex mcp remove swordfish 2>/dev/null || true
codex mcp add swordfish -- "$PROJECT_DIR/docker-run-over-ssh.sh" swordfish --headless-mcp --allow-compile --allow-tracing
codex mcp list --json
```

Add `--allow-eval` and `--allow-commit` to enable evaluation and transaction
commits; both require explicit human confirmation at each call.

## Configuration

Swordfish stores its configuration in `~/.config/swordfish/swordfish.json`
(or `$XDG_CONFIG_HOME/swordfish/swordfish.json` if set). Most settings are
editable via the GUI; the sections below cover config-file-only options.

### GemStone executable configuration file

`gemstone_exe_conf` sets the `GEMSTONE_EXE_CONF` environment variable at
process startup, pointing GemStone to a specific executable configuration
file. This is a process-level setting that takes effect before any session
is opened. If `GEMSTONE_EXE_CONF` is already set in the environment and the
config file specifies a different path, the config file wins and a warning is
logged.

```json
{
  "schema_version": 2,
  "gemstone_exe_conf": "/path/to/gemstone.conf"
}
```

### MCP runtime permissions

The `mcp_runtime_config` section controls which MCP capabilities are active.
These can also be set at startup via command-line flags (`--allow-compile`,
`--allow-eval`, etc.) or toggled in the GUI's MCP menu.

```json
{
  "schema_version": 2,
  "mcp_runtime_config": {
    "allow_source_read": true,
    "allow_source_write": false,
    "allow_eval_arbitrary": false,
    "allow_test_execution": false,
    "allow_ide_read": true,
    "allow_ide_write": false,
    "allow_commit": false,
    "allow_tracing": false,
    "require_gemstone_ast": false,
    "mcp_host": "127.0.0.1",
    "mcp_port": 8000,
    "mcp_http_path": "/mcp"
  }
}
```

### Locking permissions for protected databases

If the config file is read-only, `mcp_permission_policy` controls whether
users can still change MCP permission toggles for the current session. The
Smalltalk expression must evaluate to `true` (session changes allowed) or
`false` (all toggles locked). Swordfish fails closed if the expression errors
or returns a non-boolean.

```json
{
  "schema_version": 2,
  "mcp_permission_policy": {
    "allow_session_permission_changes_condition_source": "System stoneName ~= 'prod'"
  }
}
```

### Run GemStone code on login

A `login` script is evaluated immediately after a successful GemStone login,
before the IDE opens. If the script raises an error, login is aborted and the
session is closed.

```json
{
  "schema_version": 2,
  "login": {
    "gemstone_script_source": "System stoneName"
  }
}
```

## Requirements

- Python 3.6+
- Tcl/Tk
- reahl-parseltongue
- Access to a GemStone/Smalltalk environment

## AI-Assisted Development

This project serves as an exploration of how AI can be incorporated into software development workflows. Our key insights include:

- The initial framework of the app was developed entirely by prompting the AI.
- As the codebase grew, we started refactoring to extract duplication and address other important code smells.
- We introduced an event-handling mechanism to allow for better design regarding event handling.
- We found that refactoring helps tremendously by allowing us to give the AI smaller relevant chunks of context to work with.

Throughout the process, human developers provided domain expertise, drove architectural decisions, performed code reviews, and handled integration and testing. The project demonstrates how AI can be an effective collaborator in software development when combined with sound software engineering practices.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

GemStone/S is proprietary software by GemTalk Systems and is not distributed as part of this project. You must obtain and use GemStone/S under separate GemTalk license terms. No rights to GemStone/S are granted by this project's GPL license.

## Development & CI/CD

### Continuous Integration

This project uses GitHub Actions for continuous integration and deployment:

- **CI Workflow**: Automatically runs on pull requests and pushes to main branch
  - Tests package installation across Python 3.8-3.12
  - Validates code formatting with Black and isort
  - Builds wheel packages for verification
  - Runs import tests

- **Deploy Workflow**: Automatically publishes to PyPI on version tags
  - Triggers on tags matching `v*` pattern (e.g., `v1.0.0`)
  - Builds wheel and source distributions
  - Publishes to PyPI using secure token authentication
  - Creates GitHub releases with auto-generated notes

### Release Process

To create a new release:

1. Update the version in `src/reahl/swordfish/__init__.py`
2. Commit your changes and push to main branch
3. Create and push a version tag:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
4. The GitHub Actions workflow will automatically:
   - Build the package
   - Publish to PyPI as `reahl-swordfish`
   - Create a GitHub release

### Repository Setup

To enable automated PyPI publishing, the repository must have a `PYPI_API_TOKEN` secret configured with a valid PyPI API token for the `reahl-swordfish` package.

## Contributing

We welcome contributions! Please feel free to submit a Pull Request or submit an Issue.

## About Reahl Software Services

Reahl Software Services (Pty) Ltd is a software development company specializing in innovative software solutions. For more information, visit [our website](https://www.reahl.org/).

## How to Develop (Docker)

This section applies to both IDE and MCP workflows.

### Start the development container

```bash
# Clone the repository
git clone https://github.com/reahl/swordfish.git
cd swordfish

# Start the development environment
./docker-start.sh
```

Docker script options:

```bash
./docker-start.sh                    # Normal development mode
./docker-start.sh --no-cache         # Clean rebuild (clears Docker cache)
./docker-start.sh --foreground       # Foreground shell with entrypoint setup
./docker-start.sh --foreground --no-entry-point  # Root shell without entrypoint setup
./docker-start.sh --enable-ssh       # Start sshd in container (key-only auth)
./docker-start.sh --enable-ssh --ssh-pubkey-file ~/.ssh/id_ed25519.pub
./docker-start.sh --gemstone-version 3.6.5
```

The Docker setup includes:
- Ubuntu 24.04 base with Python 3.12
- GemStone/Smalltalk environment (default `3.7.4.3`, configurable)
- Python development tools (black, isort, pytest) in virtual environment
- X11 forwarding for GUI applications
- Volume mounts for live code editing
- Automatic user mapping for file permissions
- Entry-point setup that adds `~/.local/venv/bin` to `PATH` and loads GemStone environment in interactive shells

### SSH access for automated commands

```bash
# Start container with sshd enabled and your public key provisioned
./docker-start.sh --enable-ssh --ssh-pubkey-file ~/.ssh/id_ed25519.pub

# Optional overrides
export SF_SSH_PORT=2222
export SF_SSH_BIND_ADDRESS=127.0.0.1
export SF_MCP_PORT=9177
export SF_MCP_BIND_ADDRESS=127.0.0.1
```

Run commands from the host (recommended):

```bash
# Run any command in /workspace with ~/.local/venv activated
./docker-run-over-ssh.sh python -V
./docker-run-over-ssh.sh pytest -q

# Convenience wrapper for pytest
./docker-test-over-ssh.sh
./docker-test-over-ssh.sh tests/test_mcp_session_registry.py -q
```

Optional direct SSH session for troubleshooting:

```bash
ssh -p 2222 "$(whoami)"@127.0.0.1
```

### GemStone server management

Once inside the container, you can start and manage the GemStone server:

```bash
# Start the GemStone server (stone name: gs64stone)
sudo -u gemstone bash -l -c "startstone gs64stone"

# Check server status
sudo -u gemstone bash -l -c "gslist"

# Stop the GemStone server
sudo -u gemstone bash -l -c "stopstone gs64stone"

# Alternative: Interactive gemstone user session
sudo -u gemstone -i
```

Note: GemStone server operations must be run as the `gemstone` user for proper permissions and security. The `-l` flag ensures the GemStone environment is loaded.

### Run the IDE inside the container

When started normally (without `--no-entry-point`), the container entrypoint sets up your shell environment for Swordfish:

- `~/.local/venv/bin` is added to `PATH`
- GemStone environment is loaded for interactive shells (including `GEMSTONE`)

If you bypass the entrypoint (for example `--no-entry-point`), configure the environment manually:

```bash
source ~/.local/venv/bin/activate
. /opt/dev/gemstone/gemShell.sh "${GEMSTONE_VERSION:-3.7.4.3}"
```

To run and test specifically against GemStone `3.6.5`:

```bash
GEMSTONE_VERSION=3.6.5 ./docker-start.sh --no-cache --enable-ssh --ssh-pubkey-file ~/.ssh/id_ed25519.pub
./docker-test-over-ssh.sh
```

```bash
# 1. Start the GemStone server
sudo -u gemstone bash -l -c "startstone gs64stone"

# 2. Verify the stone is running
sudo -u gemstone bash -l -c "gslist"

# 3. Install Swordfish in development mode
pip install -e .

# 4. Run Swordfish
swordfish

# 5. In the Swordfish GUI, connect to GemStone:
#    - Use "Linked Session" connection type
#    - Set stone name to: gs64stone
#    - Leave other connection settings as defaults
```
