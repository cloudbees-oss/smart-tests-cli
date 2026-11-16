#!/usr/bin/env -S uv run --script
"""
Generate AsciiDoc documentation tables from args4p command definitions.

This script parses reference.adoc and replaces sections marked with:
    // [generate:COMMAND_PATH]
    ...
    // [/generate]

Where COMMAND_PATH is a space-separated command path like "inspect subset" or "record build".
"""

import re
import sys
from pathlib import Path
from typing import Annotated

import smart_tests.args4p.typer as typer
from smart_tests import args4p
from smart_tests.args4p.command import Command, Group
from smart_tests.args4p.converters import path
from smart_tests.args4p.exceptions import BadCmdLineException

# Add parent directory to path to import smart_tests modules
sys.path.insert(0, str(Path(__file__).parent.parent))


def resolve_command(root: Group, command_path: str) -> Command:
    current = root

    for part in command_path.strip().split():
        if not isinstance(current, Group):
            raise BadCmdLineException(f"Command '{command_path}' is invalid: '{part}' is not a group command")

        try:
            current = current.find_subcommand(part)
        except BadCmdLineException:
            raise BadCmdLineException(f"Command '{command_path}' is invalid: no such subcommand '{part}'")

    return current


def process_reference_file(reference_path: Path, cli_root: Group):
    """
    Process the reference.adoc file and replace marked sections with generated tables.

    Returns:
        The new content of the file
    """
    content = reference_path.read_text(encoding="utf-8")

    # Pattern to match: // [generate:COMMAND_PATH]
    # Captures everything until // [/generate]
    pattern = r'// \[generate:([^\]]+)\]\n(.*?)// \[/generate\]'

    def replace_section(match):
        command_path = match.group(1).strip()

        table = resolve_command(cli_root, command_path).format_asciidoc_table("smart-tests")

        return f"// [generate:{command_path}]\n{table}\n// [/generate]"

    # Replace all marked sections
    new_content = re.sub(pattern, replace_section, content, flags=re.DOTALL)

    reference_path.write_text(new_content, encoding="utf-8")
    print(f"Updated {reference_path}")


@args4p.command(help="Generate AsciiDoc documentation tables from args4p commands")
def main(reference_file: Annotated[Path, typer.Argument(type=path(exists=True, file_okay=True, dir_okay=False), required=True)]):
    """Main entry point for the script."""

    from smart_tests.__main__ import cli

    process_reference_file(reference_file, cli)


if __name__ == "__main__":
    main.main()
