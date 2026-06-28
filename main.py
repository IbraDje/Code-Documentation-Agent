import os
import sys
import json
import argparse

from dotenv import load_dotenv
from openai import OpenAI

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.prompt import Prompt

from prompts import system_prompt
from collections.abc import Callable
from agent_tools import (
    read_file, list_files, write_file, patch_file, parse_symbols,
    build_symbol_index, lookup_symbol, search_usages, get_dependency_graph,
    read_project_manifest, get_git_context, read_environment_schema,
    check_syntax, diff_file, edit_docstring,
)
from agent_tools_schemas import ALL_TOOLS

MAX_ITERS = 20
WORKING_DIR = "./project"
MODEL = "gemma4"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")

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


def call_function(tool_call, verbose: bool = False) -> dict:
    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError:
        return _make_tool_response(tool_call.id, name, "ArgsError: malformed JSON arguments.")

    if verbose:
        console.print(f"[bold cyan] ↳ {name}[/bold cyan]({args})")
    else:
        console.print(f"[cyan] ↳ {name}[/cyan]")

    if name not in TOOLS_WITH_WORKING_DIR and name not in TOOLS_STATEFUL:
        return _make_tool_response(tool_call.id, name, f"UnknownToolError: '{name}' is not a registered tool.")

    if name in TOOLS_STATEFUL:
        if name == "lookup_symbol":
            if not session["symbol_index"]:
                return _make_tool_response(tool_call.id, name,
                    "StateError: symbol index is empty. Call build_symbol_index first.")
            result = lookup_symbol(symbol_name=args.get("symbol_name", ""), index=session["symbol_index"])
        else:
            result = TOOLS_STATEFUL[name](**args)
        return _make_tool_response(tool_call.id, name, _serialize_result(result))

    fn = TOOLS_WITH_WORKING_DIR[name]
    if name == "build_symbol_index":
        raw = fn(WORKING_DIR, **args)
        if isinstance(raw, tuple):
            summary, index = raw
            session["symbol_index"] = index
            result = summary
        else:
            result = raw
    else:
        result = fn(WORKING_DIR, **args)

    if verbose and isinstance(result, dict):
        console.print(f"[dim] → {json.dumps(result, indent=2)}[/dim]")
    elif verbose:
        preview = str(result)[:300].replace("\n", " ")
        console.print(f"[dim] → {preview}{'…' if len(str(result)) > 300 else ''}[/dim]")

    return _make_tool_response(tool_call.id, name, _serialize_result(result))


def _make_tool_response(tool_call_id: str, name: str, result_str: str) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": result_str}


# ─────────────────────────────────────────────
# Gemini call  (single agentic loop, one user turn)
# ─────────────────────────────────────────────

def run_agent(client: OpenAI, messages: list[dict], verbose: bool) -> str | None:
    for i in range(MAX_ITERS):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=ALL_TOOLS,
        )
        msg = response.choices[0].message

        if verbose and response.usage:
            console.print(
                f"[dim]tokens — prompt: {response.usage.prompt_tokens} "
                f"| response: {response.usage.completion_tokens}[/dim]"
            )

        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content

        for tc in msg.tool_calls:
            messages.append(call_function(tc, verbose=verbose))

    console.print("[bold yellow]⚠ Agent interrupted: maximum iterations reached.[/bold yellow]")
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


def repl(client: OpenAI, initial_prompt: str | None, verbose: bool) -> None:
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    print_banner()
    pending = initial_prompt
    while True:
        if pending is not None:
            user_input, pending = pending, None
            console.print(f"[bold green]You:[/bold green] {user_input}")
        else:
            try:
                user_input = Prompt.ask("\n[bold green]You[/bold green]").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/dim]")
                break
        if not user_input:
            continue
        if user_input.startswith("/"):
            cmd = user_input.lower().strip()
            if cmd in ("/exit", "/quit", "/q"):
                console.print("[dim]Goodbye.[/dim]")
                break
            elif cmd == "/clear":
                messages = [{"role": "system", "content": system_prompt}]
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
        messages.append({"role": "user", "content": user_input})
        result = run_agent(client, messages, verbose)
        if result:
            print_response(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Documentation Agent")
    parser.add_argument("prompt", nargs="?", default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    cli = parser.parse_args()

    load_dotenv()
    client = OpenAI(
        base_url=os.environ.get("OLLAMA_BASE_URL", OLLAMA_BASE_URL),
        api_key=os.environ.get("OLLAMA_API_KEY", "ollama"),  # required by SDK, ignored by Ollama
    )
    repl(client, initial_prompt=cli.prompt, verbose=cli.verbose)


if __name__ == "__main__":
    main()

