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

Swordfish now includes an MCP server entrypoint named `swordfish-mcp`.

### Install MCP dependencies

```bash
pip install -e ".[mcp]"
```

### Run the server

```bash
swordfish-mcp
```

### Add MCP to Claude Code and Codex (Docker-over-SSH)

For Docker and SSH setup details used by this flow, see `How to Develop (Docker)` at the end of this README.

Start the development container with SSH enabled in one terminal and keep it running:

```bash
./docker-start.sh --enable-ssh --ssh-pubkey-file ~/.ssh/id_ed25519.pub --foreground
```

In another terminal, from the project root, configure MCP clients to launch
`swordfish-mcp` through `docker-run-over-ssh.sh`:

```bash
PROJECT_DIR="$(pwd)"

# Claude Code
claude mcp remove -s project swordfish 2>/dev/null || true
claude mcp add -s project swordfish -- "$PROJECT_DIR/docker-run-over-ssh.sh" swordfish-mcp --allow-compile --allow-tracing
claude mcp list

# Codex
codex mcp remove swordfish 2>/dev/null || true
codex mcp add swordfish -- "$PROJECT_DIR/docker-run-over-ssh.sh" swordfish-mcp --allow-compile --allow-tracing
codex mcp list --json
```

Add `--allow-eval` to enable read-only evaluation.
Add `--allow-eval-write` only when you explicitly want write-capable eval
(requires `--allow-commit`).
Add `--allow-commit` only when you explicitly want transactions to persist.
Add `--require-gemstone-ast` to enforce AST-strict refactoring mode; when
enabled, heuristic refactoring tools are blocked unless real GemStone AST
adapter support is available. In strict mode, refactoring actions attempt an
automatic AST support install/refresh when possible.
For new AI sessions, call `gs_capabilities` first to discover active policy
switches and available workflows, then call `gs_guidance` for task-specific
tool selection and sequencing.
For normal browse/edit/test workflows, prefer explicit tools like:
`gs_create_class`, `gs_create_test_case_class`, `gs_compile_method`, and
`gs_run_gemstone_tests`.
For selector exploration, use `gs_find_implementors` and `gs_find_senders`
instead of free-form evaluation. Both support `max_results` and `count_only`.
For method-level semantic navigation, use `gs_method_ast`,
`gs_method_sends`, `gs_method_structure_summary`, and
`gs_method_control_flow_summary` to inspect statement structure, send sites,
structural counts, and control-flow signals.
For versioned image support of AST helpers, use `gs_ast_status` to inspect
manifest/hash status and `gs_ast_install` to install or refresh AST support
code in the connected GemStone image.
For pattern-based method discovery across a scope, use
`gs_query_methods_by_ast_pattern` and tune ranking with `sort_by` /
`sort_descending`.
For class-scoped method renames, use `gs_preview_rename_method` and
`gs_apply_rename_method` instead of a global selector rename.
For class-scoped method moves, use `gs_preview_move_method` before
`gs_apply_move_method`, and review sender warnings before deleting the source.
For class-scoped parameter addition with compatibility forwarding, use
`gs_preview_add_parameter` then `gs_apply_add_parameter`.
For class-scoped parameter removal with compatibility forwarding, use
`gs_preview_remove_parameter` then `gs_apply_remove_parameter`; when you want
to update same-class callers immediately, set `rewrite_source_senders=true`.
For statement-level method extraction in one class/side, use
`gs_preview_extract_method` then `gs_apply_extract_method`.
For conservative unary self-send inline in one caller method, use
`gs_preview_inline_method` then `gs_apply_inline_method`.
For optional tracer installation, use `gs_tracer_install` and verify with
`gs_tracer_status` before enabling via `gs_tracer_enable`.
For runtime caller evidence, use `gs_tracer_trace_selector`, run your tests,
then query `gs_tracer_find_observed_senders`.
Tracer and evidence tools require MCP startup with `--allow-tracing`.
Use `gs_plan_evidence_tests` to build a static candidate test superset and
`gs_collect_sender_evidence` to run that plan and collect observed callers.
When you do use `gs_eval`, pass `unsafe=True` (and optionally a `reason`).
In read-only eval mode, write-like eval sources are blocked by policy.
Write tools require an explicit transaction: call `gs_begin` before writes,
then `gs_commit` (or `gs_abort`) when done. With default policy,
`gs_commit` is disabled unless the MCP server is started with
`--allow-commit`.

The server identifies itself as `SwordfishMCP` and currently supports:

- `gs_connect`
- `gs_disconnect`
- `gs_begin`
- `gs_begin_if_needed`
- `gs_commit`
- `gs_abort`
- `gs_transaction_status`
- `gs_capabilities`
- `gs_guidance`
- `gs_list_packages`
- `gs_list_classes`
- `gs_list_method_categories`
- `gs_list_methods`
- `gs_get_method_source`
- `gs_find_classes`
- `gs_find_selectors`
- `gs_find_implementors`
- `gs_find_senders`
- `gs_ast_status`
- `gs_ast_install`
- `gs_method_ast`
- `gs_method_sends`
- `gs_method_structure_summary`
- `gs_method_control_flow_summary`
- `gs_query_methods_by_ast_pattern`
- `gs_preview_rename_method`
- `gs_apply_rename_method`
- `gs_preview_move_method`
- `gs_apply_move_method`
- `gs_preview_add_parameter`
- `gs_apply_add_parameter`
- `gs_preview_remove_parameter`
- `gs_apply_remove_parameter`
- `gs_preview_extract_method`
- `gs_apply_extract_method`
- `gs_preview_inline_method`
- `gs_apply_inline_method`
- `gs_tracer_status`
- `gs_tracer_install`
- `gs_tracer_enable`
- `gs_tracer_disable`
- `gs_tracer_uninstall`
- `gs_tracer_trace_selector`
- `gs_tracer_untrace_selector`
- `gs_tracer_clear_observed_senders`
- `gs_tracer_find_observed_senders`
- `gs_plan_evidence_tests`
- `gs_collect_sender_evidence`
- `gs_create_class`
- `gs_create_test_case_class`
- `gs_get_class_definition`
- `gs_delete_class`
- `gs_compile_method`
- `gs_delete_method`
- `gs_set_method_category`
- `gs_preview_selector_rename`
- `gs_apply_selector_rename`
- `gs_list_test_case_classes`
- `gs_run_tests_in_package`
- `gs_run_test_method`
- `gs_global_set`
- `gs_global_remove`
- `gs_global_exists`
- `gs_run_gemstone_tests`
- `gs_debug_eval`
- `gs_debug_stack`
- `gs_debug_continue`
- `gs_debug_step_over`
- `gs_debug_step_into`
- `gs_debug_step_through`
- `gs_debug_stop`
- `gs_eval`

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
./docker-start.sh --foreground       # Debug mode (bypass entrypoint, root shell)
./docker-start.sh --enable-ssh       # Start sshd in container (key-only auth)
./docker-start.sh --enable-ssh --ssh-pubkey-file ~/.ssh/id_ed25519.pub
```

The Docker setup includes:
- Ubuntu 24.04 base with Python 3.12
- GemStone/Smalltalk 3.7.4.3 environment
- Python development tools (black, isort, pytest) in virtual environment
- X11 forwarding for GUI applications
- Volume mounts for live code editing
- Automatic user mapping for file permissions

### SSH access for automated commands

```bash
# Start container with sshd enabled and your public key provisioned
./docker-start.sh --enable-ssh --ssh-pubkey-file ~/.ssh/id_ed25519.pub

# Optional overrides
export SF_SSH_PORT=2222
export SF_SSH_BIND_ADDRESS=127.0.0.1
```

Then connect from the host:

```bash
ssh -p 2222 "$(whoami)"@127.0.0.1
```

Run tests through SSH:

```bash
ssh -p 2222 "$(whoami)"@127.0.0.1 'cd /workspace && source ~/.local/venv/bin/activate && pytest -q'
```

Or use project wrappers from the host:

```bash
# Run any command in /workspace with ~/.local/venv activated
./docker-run-over-ssh.sh python -V
./docker-run-over-ssh.sh pytest -q

# Convenience wrapper for pytest
./docker-test-over-ssh.sh
./docker-test-over-ssh.sh tests/test_mcp_session_registry.py -q
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
