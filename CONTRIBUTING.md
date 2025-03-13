# Contributing to Swordfish

Thank you for your interest in contributing to Swordfish! We appreciate your help in making this project better.

## Getting Started

### Prerequisites

- Python 3.6 or higher
- Git
- Tcl/Tk
- Parseltongue (proprietary dependency)
- Access to a GemStone/Smalltalk environment

### Setup for Development

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/your-username/swordfish.git
   cd swordfish
   ```
3. Set up a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
4. Install the package in development mode:
   ```bash
   pip install -e .
   ```

## Project Structure

The project follows this structure:
```
swordfish/
├── LICENSE
├── README.md
├── CONTRIBUTING.md
├── pyproject.toml
├── .gitignore
├── src/
│   └── swordfish/            # Python package directory
│       ├── __init__.py       # Makes it a proper package
│       └── main.py           # Main application code with entry point
└── tests/
    ├── __init__.py
    └── test_swordfish.py     # Tests
```

## Development Workflow

### Branching Strategy

- `main` branch is the stable branch
- Create feature branches from `main` for your work
- Use descriptive names for your branches (e.g., `feature/class-browser-improvements`, `fix/method-editor-bug`)

### Coding Standards

- Follow PEP 8 style guidelines
- Add docstrings to functions and classes
- Keep functions focused and reasonably sized
- Use meaningful variable and function names

### Commit Guidelines

- Write clear, concise commit messages
- Reference issue numbers in commit messages when applicable
- Make small, focused commits rather than large, sweeping changes

### Testing

While the project currently has minimal tests, we plan to add more. When adding new functionality:

- Create corresponding tests in the `tests/` directory
- Run tests using pytest: `pytest tests/`
- Ensure your changes don't break existing functionality

### Pull Requests

1. Update your feature branch with the latest changes from `main`
2. Run tests to ensure your changes don't break existing functionality
3. Submit a pull request to the `main` branch
4. In your PR description, explain the changes and the problem they solve
5. Link any relevant issues

## Refactoring Guidelines

As noted in our development approach, refactoring is an important part of working with AI-assisted code:

1. Look for duplicated code that can be extracted into helper functions
2. Consider event-based designs for UI interactions
3. Break down large functions into smaller, more manageable components
4. Improve naming to clarify intent
5. Document your changes and the reasons behind them

## Documentation

- Update the README.md if you change functionality
- Document new features, both in code (docstrings) and in user-facing documentation
- Keep comments current when changing code

## Questions or Problems?

If you have questions or encounter problems, please:

1. Check existing issues on GitHub
2. Create a new issue if needed
3. Contact the maintainers at [info@reahl.org](mailto:info@reahl.org)

Thank you for contributing to Swordfish!
