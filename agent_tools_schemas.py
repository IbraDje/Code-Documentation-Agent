"""OpenAI/Ollama-compatible tool schemas for all agent tools."""

from agent_tools import MAX_CHARS


def _tool(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


schema_read_file = _tool(
    "read_file",
    f"Reads and returns the text content of a file (up to {MAX_CHARS} characters). "
    "Use this to inspect any source file, config, or document before editing it.",
    {"file_path": {"type": "string", "description": "Path to the file to read, relative to the working directory."}},
    ["file_path"],
)

schema_list_files = _tool(
    "list_files",
    "Recursively lists files inside the working directory that match a glob pattern. "
    "Noise directories (node_modules, __pycache__, .git, .venv, dist, build, etc.) are excluded automatically.",
    {
        "directory": {"type": "string", "description": "Root directory to search from. Defaults to '.'."},
        "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'. Defaults to '**/*'."},
    },
    [],
)

schema_write_file = _tool(
    "write_file",
    "Writes content to a file, creating missing parent directories. Refuses to overwrite unless told to. "
    "Use patch_file for small edits instead.",
    {
        "file_path": {"type": "string", "description": "Path to write to."},
        "content": {"type": "string", "description": "Full text content to write."},
        "overwrite": {"type": "boolean", "description": "Set True to replace an existing file. Defaults to False."},
    },
    ["file_path", "content"],
)

schema_patch_file = _tool(
    "patch_file",
    "Replaces a specific section of an existing file. The match must be byte-for-byte exact.",
    {
        "file_path": {"type": "string", "description": "Path to the file to modify."},
        "old_content": {"type": "string", "description": "Exact string to find and replace."},
        "new_content": {"type": "string", "description": "String to insert in place of old_content."},
        "allow_multiple": {"type": "boolean", "description": "Allow replacing all occurrences. Defaults to False."},
    },
    ["file_path", "old_content", "new_content"],
)

schema_parse_symbols = _tool(
    "parse_symbols",
    "Parses a Python file with the AST and returns all classes/functions/methods with name, type, "
    "line number, parent class, docstring, and args.",
    {"file_path": {"type": "string", "description": "Path to the Python file to parse."}},
    ["file_path"],
)

schema_build_symbol_index = _tool(
    "build_symbol_index",
    "Walks the working directory and builds a project-wide symbol index. Call once per session.",
    {"pattern": {"type": "string", "description": "Glob pattern to select files. Defaults to '**/*.py'."}},
    [],
)

schema_lookup_symbol = _tool(
    "lookup_symbol",
    "Looks up a symbol by name in the index built by build_symbol_index.",
    {"symbol_name": {"type": "string", "description": "Name of the symbol, e.g. 'UserProfile'."}},
    ["symbol_name"],
)

schema_search_usages = _tool(
    "search_usages",
    "Searches files for lines referencing a given symbol.",
    {
        "symbol_name": {"type": "string", "description": "Symbol name to search for."},
        "pattern": {"type": "string", "description": "Glob pattern. Defaults to '**/*.py'."},
    },
    ["symbol_name"],
)

schema_get_dependency_graph = _tool(
    "get_dependency_graph",
    "Resolves imports across files and builds a dependency graph, detecting circular imports.",
    {"pattern": {"type": "string", "description": "Glob pattern. Defaults to '**/*.py'."}},
    [],
)

schema_read_project_manifest = _tool(
    "read_project_manifest",
    "Parses package.json / pyproject.toml / setup.py / Cargo.toml for README metadata.",
    {"project_root": {"type": "string", "description": "Root directory to inspect. Defaults to '.'."}},
    [],
)

schema_get_git_context = _tool(
    "get_git_context",
    "Extracts recent commits, latest tag, and top contributors for README sections.",
    {
        "project_root": {"type": "string", "description": "Root of the git repo. Defaults to '.'."},
        "max_commits": {"type": "integer", "description": "Max commits to return. Defaults to 20."},
    },
    [],
)

schema_read_environment_schema = _tool(
    "read_environment_schema",
    "Parses .env.example/.env.sample/etc. to generate a Configuration section.",
    {"project_root": {"type": "string", "description": "Root to search. Defaults to '.'."}},
    [],
)

schema_check_syntax = _tool(
    "check_syntax",
    "Verifies a Python file is syntactically valid after editing. Always call after write/patch.",
    {"file_path": {"type": "string", "description": "Path to the Python file to validate."}},
    ["file_path"],
)

schema_diff_file = _tool(
    "diff_file",
    "Produces a unified diff between current file content and a proposed new version.",
    {
        "file_path": {"type": "string", "description": "Path to the existing file."},
        "new_content": {"type": "string", "description": "Proposed new content."},
    },
    ["file_path", "new_content"],
)

schema_edit_docstring = _tool(
    "edit_docstring",
    "Replaces, inserts, or removes a function/method/class docstring via AST, no verbatim text needed.",
    {
        "file_path": {"type": "string", "description": "Path to the Python file."},
        "function_name": {"type": "string", "description": "Name of the function/method/class."},
        "new_docstring": {"type": "string", "description": "New docstring text, no quotes/indentation."},
        "parent_class": {"type": "string", "description": "Enclosing class, for disambiguating methods."},
    },
    ["file_path", "function_name", "new_docstring"],
)

# Pass directly as `tools=ALL_TOOLS` to client.chat.completions.create(...)
ALL_TOOLS = [
    schema_read_file,
    schema_list_files,
    schema_write_file,
    schema_patch_file,
    schema_parse_symbols,
    schema_build_symbol_index,
    schema_lookup_symbol,
    schema_search_usages,
    schema_get_dependency_graph,
    schema_read_project_manifest,
    schema_get_git_context,
    schema_read_environment_schema,
    schema_check_syntax,
    schema_diff_file,
    schema_edit_docstring,
]