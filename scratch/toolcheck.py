"""
PURPOSE:     Verify the Sam v1 toolchain is installed and on PATH, and print
             the version of each tool. Zero-dependency sanity check that
             runs before any build that needs Foundry, Rust, or Node.
INPUTS:      None. Reads only the current shell environment (PATH).
OUTPUTS:     A human-readable report to stdout, one row per tool, with a
             green OK / red MISSING marker and the reported version string.
             Exit code 0 if every tool is present, 1 if any are missing.
ASSUMPTIONS: macOS + zsh/bash. Tools are the v1 stack installed on
             2026-04-18: Homebrew, Node, Foundry (forge/cast/anvil), Rust
             (rustc/cargo). No network calls. No install logic — this
             script only reports, it does not fix.
AUDIT NOTES: Uses only the Python standard library (subprocess, shutil,
             sys). Pure read-only. Safe to run on any machine at any time.
"""

# ----------------------------------------------------------------------------
# TEACHING NOTE — the `subprocess` module (new territory for you)
# ----------------------------------------------------------------------------
# `subprocess` is Python's standard-library way to run another program the
# same way your shell would — as if you typed `forge --version` at the
# terminal yourself. It is part of Python; nothing to `pip install`.
#
# The idea is simple: Python launches a *child process*, hands it a command
# + arguments, and captures what that child prints (stdout) and any error
# text (stderr). When the child finishes, Python gets the exit code (0 for
# success, non-zero for failure — a UNIX convention you'll see forever).
#
# The modern, recommended function is `subprocess.run(...)`. Key arguments:
#   - args:           a LIST like ["forge", "--version"]. Pass a list, not a
#                     single string — this avoids shell-injection bugs.
#   - capture_output: True tells Python to collect stdout/stderr instead of
#                     letting them print straight to your terminal.
#   - text:           True decodes bytes to a normal str (UTF-8 by default).
#                     Without this you get raw bytes, which is annoying.
#   - timeout:        seconds before Python kills the child. A safety net
#                     so a hung tool can never freeze this script.
#   - check:          if True, raises an exception on non-zero exit. We
#                     leave it False and inspect .returncode ourselves so
#                     we can report gracefully.
#
# Why we ALSO use `shutil.which(...)` first: it checks whether a command
# exists on PATH *without actually running it*. That is both faster and
# safer than trying to run a binary that isn't there (which raises
# FileNotFoundError). Check presence first, then ask for version.
#
# Compared to the old `os.system("forge --version")`: `subprocess.run` is
# safer (argument list, no shell parsing), gives you the output as data,
# and is the idiom every modern Python codebase uses.
# ----------------------------------------------------------------------------

import shutil
import subprocess
import sys
from dataclasses import dataclass

# ANSI color escape codes — purely cosmetic. `\033[...m` is read by most
# modern terminals (including macOS Terminal and iTerm2) as "change color".
GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass
class Tool:
    """One row of the toolchain report.

    name:         display label (what we call the tool in prose).
    command:      the binary name we expect to find on PATH.
    version_args: the argv tail that makes the tool print its version.
                  Different tools disagree: node uses '--version', rustc
                  uses '--version', forge uses '--version', brew uses
                  '--version'. We keep it explicit per-tool anyway, so
                  future additions (e.g., a tool that needs 'version'
                  with no dashes) slot in without special-casing.
    """

    name: str
    command: str
    version_args: list[str]


# The v1 toolchain, in the order we want the report to read.
TOOLS: list[Tool] = [
    Tool("Homebrew",      "brew",   ["--version"]),
    Tool("Node.js",       "node",   ["--version"]),
    Tool("npm",           "npm",    ["--version"]),   # ships with Node
    Tool("Foundry: forge", "forge", ["--version"]),
    Tool("Foundry: cast", "cast",   ["--version"]),
    Tool("Foundry: anvil", "anvil", ["--version"]),
    Tool("Rust: rustc",   "rustc",  ["--version"]),
    Tool("Rust: cargo",   "cargo",  ["--version"]),
]


def check_tool(tool: Tool) -> tuple[bool, str]:
    """Return (present, reported_version_or_error_message).

    Two failure modes we need to handle distinctly:
      1. Command not on PATH at all  -> shutil.which returns None.
      2. Command exists but misbehaves (non-zero exit, hang, garbage
         output) -> subprocess.run tells us via returncode / exception.
    """
    # --- Step 1: is it even on PATH? ---------------------------------------
    # shutil.which is the Python equivalent of the shell's `which` builtin.
    # Returns the absolute path to the binary, or None if not found.
    resolved_path = shutil.which(tool.command)
    if resolved_path is None:
        return (False, f"not found on PATH (looked for '{tool.command}')")

    # --- Step 2: run it and capture the version ----------------------------
    try:
        result = subprocess.run(
            [tool.command, *tool.version_args],
            capture_output=True,   # collect stdout + stderr
            text=True,             # decode bytes to str
            timeout=10,            # kill if it hangs past 10s
            check=False,           # don't raise on non-zero; we inspect it
        )
    except subprocess.TimeoutExpired:
        return (False, "timed out after 10s while asking for version")
    except OSError as e:
        # Defensive: covers weird cases like a broken symlink or perms.
        return (False, f"OS error launching command: {e}")

    if result.returncode != 0:
        # Some tools (older versions of certain CLIs) print to stderr even
        # on success, but a non-zero exit is a real signal.
        err = (result.stderr or result.stdout or "").strip()
        return (False, f"exit code {result.returncode}: {err[:120]}")

    # Tools vary on which stream carries the version; prefer stdout, fall
    # back to stderr. Take only the first non-empty line — `brew --version`
    # prints multiple lines and we want the headline.
    raw = (result.stdout or result.stderr or "").strip()
    first_line = next((ln for ln in raw.splitlines() if ln.strip()), "(empty output)")
    return (True, first_line)


def main() -> int:
    print(f"{DIM}Sam v1 toolchain check — {RESET}"
          f"{len(TOOLS)} tools, macOS, Python {sys.version.split()[0]}")
    print("-" * 72)

    any_missing = False
    # Pad the name column so versions line up visually.
    name_col_width = max(len(t.name) for t in TOOLS)

    for tool in TOOLS:
        ok, message = check_tool(tool)
        if ok:
            marker = f"{GREEN}OK     {RESET}"
        else:
            marker = f"{RED}MISSING{RESET}"
            any_missing = True
        print(f"  {marker}  {tool.name:<{name_col_width}}  {message}")

    print("-" * 72)
    if any_missing:
        print(f"{RED}One or more tools missing. Fix before running any v1 build.{RESET}")
        return 1
    print(f"{GREEN}All v1 tools present. Ready to build.{RESET}")
    return 0


if __name__ == "__main__":
    # sys.exit passes our return code up to the shell, so CI or a Makefile
    # can branch on success/failure. A habit worth forming early.
    sys.exit(main())
