"""
Gemini FunctionDeclaration schemas for all agent tools.

Each schema exposes only the parameters the agent controls.
- `working_dir` is always omitted (injected server-side as a jail constraint).
- `index` in lookup_symbol is omitted (injected server-side from build_symbol_index output).
"""

from google.genai import types
from agent_tools import MAX_CHARS


# ─────────────────────────────────────────────
# FILE SYSTEM TOOLS
# ─────────────────────────────────────────────

schema_read_file = types.FunctionDeclaration(
    name="read_file",
    description=(
        f"Reads and returns the text content of a file (up to {MAX_CHARS} characters). "
        "Use this to inspect any source file, config, or document before editing it."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "file_path": types.Schema(
                type=types.Type.STRING,
                description="Path to the file to read, relative to the working directory.",
            ),
        },
        required=["file_path"],
    ),
)

schema_list_files = types.FunctionDeclaration(
    name="list_files",
    description=(
        "Recursively lists files inside the working directory that match a glob pattern. "
        "Noise directories (node_modules, __pycache__, .git, .venv, dist, build, etc.) "
        "are excluded automatically. Use this to discover source files before reading them."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "directory": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Root directory to search from, relative to the working directory. "
                    "Defaults to the working directory root ('.')."
                ),
            ),
            "pattern": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Glob pattern to filter results. "
                    "Examples: '**/*.py', '**/*.ts', 'src/**/*.js'. "
                    "Defaults to '**/*' (all files)."
                ),
            ),
        },
        required=[],
    ),
)

schema_write_file = types.FunctionDeclaration(
    name="write_file",
    description=(
        "Writes content to a file, creating any missing parent directories. "
        "By default refuses to overwrite an existing file to prevent accidental data loss. "
        "Use patch_file instead when you only need to change a small section of an existing file."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "file_path": types.Schema(
                type=types.Type.STRING,
                description="Path to the file to write, relative to the working directory.",
            ),
            "content": types.Schema(
                type=types.Type.STRING,
                description="Full text content to write to the file.",
            ),
            "overwrite": types.Schema(
                type=types.Type.BOOLEAN,
                description=(
                    "If True, replaces the file if it already exists. "
                    "Defaults to False. Set to True only when intentionally replacing an existing file."
                ),
            ),
        },
        required=["file_path", "content"],
    ),
)

schema_patch_file = types.FunctionDeclaration(
    name="patch_file",
    description=(
        "Replaces a specific section of an existing file without rewriting the whole thing. "
        "Prefer this over write_file for targeted edits such as updating a docstring or "
        "inserting a new function. The match must be byte-for-byte exact (whitespace included)."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "file_path": types.Schema(
                type=types.Type.STRING,
                description="Path to the file to modify, relative to the working directory.",
            ),
            "old_content": types.Schema(
                type=types.Type.STRING,
                description=(
                    "The exact string to find and replace. "
                    "Must match the file content character-for-character, including all whitespace."
                ),
            ),
            "new_content": types.Schema(
                type=types.Type.STRING,
                description="The string to insert in place of old_content.",
            ),
            "allow_multiple": types.Schema(
                type=types.Type.BOOLEAN,
                description=(
                    "If False (default), returns an error when old_content appears more than once, "
                    "preventing unintended multi-site edits. "
                    "Set to True to replace all occurrences at once."
                ),
            ),
        },
        required=["file_path", "old_content", "new_content"],
    ),
)


# ─────────────────────────────────────────────
# CODE UNDERSTANDING TOOLS
# ─────────────────────────────────────────────

schema_parse_symbols = types.FunctionDeclaration(
    name="parse_symbols",
    description=(
        "Parses a Python source file with the AST and returns all top-level and nested symbols: "
        "classes, functions, and methods, along with their name, type, line number, parent class, "
        "existing docstring, and argument list. "
        "Use this to understand a file's structure before writing or updating docstrings."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "file_path": types.Schema(
                type=types.Type.STRING,
                description="Path to the Python source file to parse, relative to the working directory.",
            ),
        },
        required=["file_path"],
    ),
)

schema_build_symbol_index = types.FunctionDeclaration(
    name="build_symbol_index",
    description=(
        "Walks all matching source files under the working directory and builds a project-wide "
        "symbol index mapping every class, function, and method to its file, module, line, and docstring. "
        "Call this once at the start of a session; use lookup_symbol to query the result. "
        "Returns a human-readable summary of all indexed symbols."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "pattern": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Glob pattern to select which files to index. "
                    "Defaults to '**/*.py' (all Python files)."
                ),
            ),
        },
        required=[],
    ),
)

schema_lookup_symbol = types.FunctionDeclaration(
    name="lookup_symbol",
    description=(
        "Looks up a symbol by name in the project-wide index built by build_symbol_index. "
        "Tries an exact match first, then falls back to case-insensitive and partial matches, "
        "returning ranked suggestions if no exact hit is found. "
        "Use this to locate where a class or function is defined before reading or editing it."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "symbol_name": types.Schema(
                type=types.Type.STRING,
                description="Name of the symbol to search for, e.g. 'UserProfile' or 'parse_tokens'.",
            ),
        },
        required=["symbol_name"],
    ),
)

schema_search_usages = types.FunctionDeclaration(
    name="search_usages",
    description=(
        "Searches every matching file in the working directory for lines that reference a given symbol. "
        "Returns a grouped list of file paths, line numbers, and surrounding context. "
        "Useful for writing 'Used by:' sections in docstrings or confirming a refactor is safe."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "symbol_name": types.Schema(
                type=types.Type.STRING,
                description="The symbol name to search for, e.g. 'AuthToken'.",
            ),
            "pattern": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Glob pattern selecting which files to scan. "
                    "Defaults to '**/*.py'."
                ),
            ),
        },
        required=["symbol_name"],
    ),
)

schema_get_dependency_graph = types.FunctionDeclaration(
    name="get_dependency_graph",
    description=(
        "Resolves all import statements across matching source files and builds a graph of "
        "inter-file dependencies. Outputs a per-file dependency list, detects circular imports, "
        "and suggests a documentation order (leaf modules first). "
        "Use this to generate architecture sections in README files."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "pattern": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Glob pattern selecting which files to analyze. "
                    "Defaults to '**/*.py'."
                ),
            ),
        },
        required=[],
    ),
)


# ─────────────────────────────────────────────
# CONTEXT & METADATA TOOLS
# ─────────────────────────────────────────────

schema_read_project_manifest = types.FunctionDeclaration(
    name="read_project_manifest",
    description=(
        "Detects and parses the project's package manifest to extract metadata for README generation. "
        "Supports package.json (Node/npm), pyproject.toml and setup.py (Python), and Cargo.toml (Rust). "
        "Returns the project name, version, description, license, dependencies, and run scripts."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "project_root": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Root directory of the project to inspect, relative to the working directory. "
                    "Defaults to the working directory root ('.')."
                ),
            ),
        },
        required=[],
    ),
)

schema_get_git_context = types.FunctionDeclaration(
    name="get_git_context",
    description=(
        "Extracts git metadata to enrich documentation with project history. "
        "Returns recent commit messages, the latest tag/version, and top contributors "
        "for use in 'Recent Changes' and 'Authors' sections of a README."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "project_root": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Root directory of the git repository, relative to the working directory. "
                    "Defaults to the working directory root ('.')."
                ),
            ),
            "max_commits": types.Schema(
                type=types.Type.INTEGER,
                description=(
                    "Maximum number of recent commits to return. "
                    "Defaults to 20."
                ),
            ),
        },
        required=[],
    ),
)

schema_read_environment_schema = types.FunctionDeclaration(
    name="read_environment_schema",
    description=(
        "Parses environment variable definitions from .env.example, .env.sample, "
        ".env.template, or .env.defaults to auto-generate a Configuration section in the README. "
        "Returns each variable's name, default value, inline description, and whether it is required."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "project_root": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Root directory to search for an env schema file, relative to the working directory. "
                    "Defaults to the working directory root ('.')."
                ),
            ),
        },
        required=[],
    ),
)


# ─────────────────────────────────────────────
# VALIDATION TOOLS
# ─────────────────────────────────────────────

schema_check_syntax = types.FunctionDeclaration(
    name="check_syntax",
    description=(
        "Verifies that a Python source file is syntactically valid after the agent has modified it. "
        "Returns whether the file parses cleanly, and if not, the error message and line number. "
        "Always call this after writing or patching a Python file before moving on."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "file_path": types.Schema(
                type=types.Type.STRING,
                description="Path to the Python file to validate, relative to the working directory.",
            ),
        },
        required=["file_path"],
    ),
)

schema_diff_file = types.FunctionDeclaration(
    name="diff_file",
    description=(
        "Produces a unified diff between the current content of a file and a proposed new version. "
        "Returns an empty string when there are no differences, making it safe to call unconditionally. "
        "Use this before calling write_file to review what will change and avoid redundant rewrites."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "file_path": types.Schema(
                type=types.Type.STRING,
                description="Path to the existing file to compare against, relative to the working directory.",
            ),
            "new_content": types.Schema(
                type=types.Type.STRING,
                description="The proposed new content to diff against the current file.",
            ),
        },
        required=["file_path", "new_content"],
    ),
)


schema_edit_docstring = types.FunctionDeclaration(
    name="edit_docstring",
    description=(
        "Replace, insert, or remove the docstring of a function, method, or class in a Python file. "
        "Prefer this over patch_file whenever only a docstring needs to change — it uses the AST to "
        "locate the exact line span, so you never have to reproduce surrounding source text verbatim."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "file_path": types.Schema(
                type=types.Type.STRING,
                description="Path to the Python source file to edit, relative to the working directory.",
            ),
            "function_name": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Name of the function, method, or class whose docstring should be updated. "
                    "Use parse_symbols() first if you are unsure of the exact name."
                ),
            ),
            "new_docstring": types.Schema(
                type=types.Type.STRING,
                description=(
                    "The new docstring text, without triple-quotes or indentation — those are added automatically. "
                    "Pass an empty string to remove an existing docstring entirely."
                ),
            ),
            "parent_class": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Enclosing class name, required when targeting a method to disambiguate it from "
                    "a free function with the same name. Omit for top-level functions and classes."
                ),
            ),
        },
        required=["file_path", "function_name", "new_docstring"],
    ),
)


# ─────────────────────────────────────────────
# TOOL LIST  (pass directly to the Gemini API)
# ─────────────────────────────────────────────

ALL_TOOLS = types.Tool(
    function_declarations=[
        # File system
        schema_read_file,
        schema_list_files,
        schema_write_file,
        schema_patch_file,
        # Code understanding
        schema_parse_symbols,
        schema_build_symbol_index,
        schema_lookup_symbol,
        schema_search_usages,
        schema_get_dependency_graph,
        # Context & metadata
        schema_read_project_manifest,
        schema_get_git_context,
        schema_read_environment_schema,
        # Validation
        schema_check_syntax,
        schema_diff_file,
        # Docstring edit
        schema_edit_docstring,
    ]
)