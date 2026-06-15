import os
import sys
import json
import argparse

from dotenv import load_dotenv
from google import genai
from google.genai import types
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.prompt import Prompt

from prompts import system_prompt
from collections.abc import Callable

from agent_tools import (
    read_file,
    list_files,
    write_file,
    patch_file,
    parse_symbols,
    build_symbol_index,
    lookup_symbol,
    search_usages,
    get_dependency_graph,
    read_project_manifest,
    get_git_context,
    read_environment_schema,
    check_syntax,
    diff_file,
    edit_docstring
)
from agent_tools_schemas import ALL_TOOLS

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

MAX_ITERS   = 20
WORKING_DIR = "./project"
# MODEL       = "gemini-2.5-flash"
MODEL       = "gemini-3.1-flash-lite"

console = Console()

# ─────────────────────────────────────────────
# Session state  (persists across conversation turns)
# ─────────────────────────────────────────────

session: dict = {
    "symbol_index": {},   # populated by build_symbol_index, injected into lookup_symbol
}

# ─────────────────────────────────────────────
# Tool dispatcher
# ─────────────────────────────────────────────

# Tools that require working_dir injected as the first positional argument
TOOLS_WITH_WORKING_DIR: dict[str, Callable] = {
    "read_file":              read_file,
    "list_files":             list_files,
    "write_file":             write_file,
    "patch_file":             patch_file,
    "parse_symbols":          parse_symbols,
    "build_symbol_index":     build_symbol_index,
    "search_usages":          search_usages,
    "get_dependency_graph":   get_dependency_graph,
    "read_project_manifest":  read_project_manifest,
    "get_git_context":        get_git_context,
    "read_environment_schema":read_environment_schema,
    "check_syntax":           check_syntax,
    "diff_file":              diff_file,
    "edit_docstring":         edit_docstring,
}

# Tools that do NOT receive working_dir (use session state instead)
TOOLS_STATEFUL: dict[str, Callable] = {
    "lookup_symbol": lookup_symbol,
}


def _serialize_result(result) -> str:
    """Normalize any tool return value to a JSON-serialisable string."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result, indent=2)
    if isinstance(result, (list, tuple)):
        return json.dumps(result, indent=2)
    return str(result)


def call_function(
    function_call: types.FunctionCall,
    verbose: bool = False,
) -> types.Content:
    name = function_call.name or ""
    args = dict(function_call.args) if function_call.args else {}

    if verbose:
        console.print(f"[bold cyan]  ↳ {name}[/bold cyan]({args})")
    else:
        console.print(f"[cyan]  ↳ {name}[/cyan]")

    # ── Unknown tool ────────────────────────────────────────────────────────
    if name not in TOOLS_WITH_WORKING_DIR and name not in TOOLS_STATEFUL:
        return _make_tool_response(name, f"UnknownToolError: '{name}' is not a registered tool.")

    # ── Stateful tools (no working_dir, use session) ─────────────────────
    if name in TOOLS_STATEFUL:
        if name == "lookup_symbol":
            if not session["symbol_index"]:
                return _make_tool_response(
                    name,
                    "StateError: symbol index is empty. Call build_symbol_index first.",
                )
            result = lookup_symbol(
                symbol_name=args.get("symbol_name", ""),
                index=session["symbol_index"],
            )
        else:
            result = TOOLS_STATEFUL[name](**args)

        return _make_tool_response(name, _serialize_result(result))

    # ── Regular tools (working_dir injected) ────────────────────────────
    fn = TOOLS_WITH_WORKING_DIR[name]

    # build_symbol_index returns (summary_str, index_dict) — store the dict in session
    if name == "build_symbol_index":
        raw = fn(WORKING_DIR, **args)
        if isinstance(raw, tuple):
            summary, index = raw
            session["symbol_index"] = index
            result = summary  # send only the readable summary to the LLM
        else:
            result = raw      # error string — pass through as-is
    else:
        result = fn(WORKING_DIR, **args)

    if verbose and isinstance(result, dict):
        console.print(f"[dim]  → {json.dumps(result, indent=2)}[/dim]")
    elif verbose:
        preview = str(result)[:300].replace("\n", " ")
        console.print(f"[dim]  → {preview}{'…' if len(str(result)) > 300 else ''}[/dim]")

    return _make_tool_response(name, _serialize_result(result))


def _make_tool_response(name: str, result_str: str) -> types.Content:
    return types.Content(
        role="tool",
        parts=[
            types.Part.from_function_response(
                name=name,
                response={"result": result_str},
            )
        ],
    )


# ─────────────────────────────────────────────
# Gemini call  (single agentic loop, one user turn)
# ─────────────────────────────────────────────

def run_agent(
    client: genai.Client,
    messages: list[types.Content],
    verbose: bool,
) -> str | None:
    """
    Run the agentic tool-call loop for the current conversation state.
    Returns the final text response, or None if the agent hit MAX_ITERS.
    """
    for i in range(MAX_ITERS):
        response = client.models.generate_content(
            model=MODEL,
            contents=messages,
            config=types.GenerateContentConfig(
                tools=[ALL_TOOLS],
                system_instruction=system_prompt,
            ),
        )

        if not response.usage_metadata:
            raise RuntimeError("Malformed Gemini API response: no usage metadata.")

        # Append every candidate turn to history
        for candidate in response.candidates or []:
            messages.append(candidate.content)

        if verbose:
            console.print(
                f"[dim]tokens — prompt: {response.usage_metadata.prompt_token_count} "
                f"| response: {response.usage_metadata.candidates_token_count}[/dim]"
            )

        # ── No tool calls → final answer ─────────────────────────────────
        if not response.function_calls:
            return response.text

        # ── Dispatch tool calls and collect results ───────────────────────
        tool_parts: list[types.Part] = []
        for fc in response.function_calls:
            content = call_function(fc, verbose=verbose)
            tool_parts.append(content.parts[0])

        messages.append(types.Content(role="tool", parts=tool_parts))

    console.print(
        "[bold yellow]⚠ Agent interrupted: maximum iterations reached.[/bold yellow]"
    )
    return None


# ─────────────────────────────────────────────
# REPL
# ─────────────────────────────────────────────

HELP_TEXT = """
[bold]Available commands[/bold]
  [cyan]/clear[/cyan]    Start a new conversation (resets history and symbol index)
  [cyan]/history[/cyan]  Show the number of messages in the current conversation
  [cyan]/verbose[/cyan]  Toggle verbose output
  [cyan]/help[/cyan]     Show this message
  [cyan]/exit[/cyan]     Quit
"""

def print_banner() -> None:
    console.print(Panel(
        "[bold white]Documentation Agent[/bold white]\n"
        f"[dim]Model: {MODEL}   Working dir: {WORKING_DIR}[/dim]\n"
        "[dim]Type [bold]/help[/bold] for commands, [bold]/exit[/bold] to quit.[/dim]",
        border_style="bright_blue",
        padding=(0, 2),
    ))


def print_response(text: str) -> None:
    console.print(Rule(style="dim"))
    console.print(Markdown(text))
    console.print()


def repl(client: genai.Client, initial_prompt: str | None, verbose: bool) -> None:
    messages: list[types.Content] = []

    print_banner()

    # Allow a one-shot prompt passed via CLI arg
    if initial_prompt:
        pending = initial_prompt
    else:
        pending = None

    while True:
        # ── Get input ────────────────────────────────────────────────────
        if pending is not None:
            user_input = pending
            pending = None
            console.print(f"[bold green]You:[/bold green] {user_input}")
        else:
            try:
                user_input = Prompt.ask("\n[bold green]You[/bold green]").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/dim]")
                break

        if not user_input:
            continue

        # ── Commands ────────────────────────────────────────────────────
        if user_input.startswith("/"):
            cmd = user_input.lower().strip()

            if cmd in ("/exit", "/quit", "/q"):
                console.print("[dim]Goodbye.[/dim]")
                break

            elif cmd == "/clear":
                messages.clear()
                session["symbol_index"] = {}
                console.print("[dim]Conversation and symbol index cleared.[/dim]")
                continue

            elif cmd == "/history":
                console.print(f"[dim]{len(messages)} message(s) in current conversation.[/dim]")
                continue

            elif cmd == "/verbose":
                verbose = not verbose
                console.print(f"[dim]Verbose {'on' if verbose else 'off'}.[/dim]")
                continue

            elif cmd == "/help":
                console.print(HELP_TEXT)
                continue

            else:
                console.print(f"[yellow]Unknown command: {user_input}[/yellow]")
                continue

        # ── Agent turn ──────────────────────────────────────────────────
        messages.append(
            types.Content(role="user", parts=[types.Part(text=user_input)])
        )

        with console.status("[bold blue]Thinking…[/bold blue]", spinner="dots"):
            # status spinner is suppressed once the first tool fires,
            # since call_function prints directly — that's intentional
            pass

        result = run_agent(client, messages, verbose)

        if result:
            print_response(result)


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Documentation Agent")
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Optional opening prompt. If omitted, starts an interactive session.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print token counts, full args, and tool result previews.",
    )
    # parser.add_argument(
    #     "--working-dir", "-w",
    #     default=WORKING_DIR,
    #     metavar="DIR",
    #     help=f"Working directory to restrict agent file access (default: {WORKING_DIR}).",
    # )
    cli = parser.parse_args()

    # Allow overriding WORKING_DIR at runtime
    # global WORKING_DIR
    # WORKING_DIR = cli.working_dir

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[bold red]Error:[/bold red] GEMINI_API_KEY is not set.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    repl(client, initial_prompt=cli.prompt, verbose=cli.verbose)


if __name__ == "__main__":
    main()
