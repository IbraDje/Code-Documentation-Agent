# Code-Documentation-Agent

An autonomous agent designed to read, understand, and document Python codebases. This tool automates the process of writing docstrings, generating project-level READMEs, and exploring code structures.

## Features

- **Automated Documentation**: Uses AST analysis to add or update docstrings.
- **Project Exploration**: Builds symbol indices and dependency graphs to understand project architecture.
- **Context-Aware Edits**: Safely patches code and manages documentation files.
- **Tool-Integrated Workflow**: Provides a suite of file system, code analysis, and validation tools for reliable operation.

## Installation

```bash
uv sync
```

## Usage

The agent is designed to interact with a codebase through a set of defined tools. It leverages the free-to-use Google Gemini LLM (`gemini-3.1-flash-lite`) to interpret source code and generate high-quality documentation following Google style guidelines.

## Architecture

The project is structured around a main controller (`main.py`) that orchestrates various tools:

- `agent_tools.py`: Core file system and code modification tools.
- `agent_tools_schemas.py`: Tool definitions for LLM interaction.
- `prompts.py`: System and task-specific prompts for the agent.

## Contributing

1. Fork the repository.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

## License

This project is licensed under the terms of the MIT license.
