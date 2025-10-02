# Swordfish

A classic Smalltalk IDE for GemStone/Smalltalk developed by Reahl Software Services.

## Overview

Swordfish is a Python-based IDE that provides a classic Smalltalk development experience for GemStone/Smalltalk. It features class/method browsing, method editing, debugging capabilities with stepping functionality, and an object inspector.

This project was developed as an experiment in AI-assisted programming, with significant portions (including this README and other metadata) generated through collaboration between human developers and AI, followed by developer refinement and refactoring.

## Features

- Class and method browsing
- Method editing
- Debugging with step execution
- Object inspection
- Classic Smalltalk IDE experience

## Technical Details

Swordfish is built with:
- Python
- Tcl/Tk for the GUI interface (implemented without prior knowledge of the toolkit)
- Parseltongue (reahl-parseltongue) - library that enables calling GemStone/Smalltalk methods from Python

## Installation

### Using Docker (Recommended for Development)

```bash
# Clone the repository
git clone https://github.com/reahl/swordfish.git
cd swordfish

# Start the development environment
./docker-start.sh

# Once inside the container, install the project in editable mode
pip install -e .

# Run the application
source ~/.profile
swordfish
```

#### Docker Script Options

```bash
./docker-start.sh                    # Normal development mode
./docker-start.sh --no-cache         # Clean rebuild (clears Docker cache)
./docker-start.sh --foreground       # Debug mode (bypass entrypoint, root shell)
```


The Docker setup includes:
- Ubuntu 24.04 base with Python 3.12
- GemStone/Smalltalk 3.7.4.3 environment  
- Python development tools (black, isort, pytest) in virtual environment
- X11 forwarding for GUI applications
- Volume mounts for live code editing
- Automatic user mapping for file permissions

#### GemStone Server Management

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

**Note**: GemStone server operations must be run as the `gemstone` user for proper permissions and security. The `-l` flag ensures the GemStone environment is loaded.

#### Running Swordfish in the Development Container

To try out Swordfish with GemStone in the development container:

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

The Swordfish GUI will open with X11 forwarding, allowing you to browse classes, edit methods, and use the debugger with your local GemStone installation.

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

## Usage

```bash
# After installation, run directly from command line
swordfish

# Or if installed from source
python -m swordfish
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

1. Update the version in `pyproject.toml`
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

We welcome contributions! Please feel free to submit a Pull Request.

## About Reahl Software Services

Reahl Software Services (Pty) Ltd is a software development company specializing in innovative software solutions. For more information, visit [our website](https://www.reahl.org/).