from __future__ import annotations

import inspect
import os
import re
import sys
from typing import Annotated, Any, Callable, List, Optional, Sequence, cast, get_args, get_origin

import click

from ..utils.edit_distance import edit_distance
from . import decorator
from .argument import Argument
from .exceptions import BadCmdLineException, BadConfigException
from .option import NO_DEFAULT, Option
from .parameter import Parameter, normalize_type, to_type
from .typer import Exit


class Command:
    parent: Group | None = None        # if this is a sub-command of another command, this is the parent command
    options: list[Option]
    arguments: list[Argument]
    name: str
    callback: Callable
    help: str | None

    def __init__(self, callback: Callable, name: str | None = None, help: str | None = None, params: Sequence[Parameter] = ()):
        self.name = name or callback.__name__.lower().replace("_", "-")
        self.help = help
        self.callback = callback

        params = list(params)
        try:
            params += reversed(callback.__args4p_params__)  # type: ignore
        except AttributeError:
            # if __args4p_params__ doesn't exist that's OK
            pass
        else:
            del callback.__args4p_params__  # type: ignore

        self.options = []
        self.arguments = []
        for p in params:
            self.add_param(p)

        # pick up parameters declared in annotations
        sig = inspect.signature(callback)
        for pname, param in sig.parameters.items():
            if get_origin(param.annotation) == Annotated:
                args = get_args(param.annotation)
                for a in args:
                    if isinstance(a, Parameter):
                        if a.name is None:
                            a.name = pname
                        if isinstance(a, Option):
                            if a.option_names is None or len(a.option_names) == 0:
                                a.option_names = [f"--{a.name.replace('_', '-')}"]
                        self.add_param(a)

    def add_param(self, param: Parameter, prepend: bool = False):
        '''
        Attach an option/argument to this command. Use this to programmatically construct Command with parameters.
        It is possible to attach the same parameter to different commands simultaneously.

        :param prepend
            when we are adding parameter from decorators, things show up in the reverse order, so we need to prepend,
            not append.
        '''
        param.attach_to_command(self)
        col = self.options if isinstance(param, Option) else self.arguments
        if prepend:
            col.insert(0, param)  # type: ignore[arg-type]
        else:
            col.append(param)   # type: ignore[arg-type]

    def __call__(self, *_args: str) -> Any:
        '''
        Given the command line arguments, parse them, bind them to the user function parameters,
        and invoke the function. This method returns the return value of the user function.
        '''
        self.check_consistency()

        invoker = _Invoker(self)
        args = ArgList(list(_args))

        while args.has_more():
            a = args.eat(None)
            if a == "--":
                # everything after this is a positional argument
                while args.has_more():
                    invoker.eat_arg(args.eat(None))
            elif a.startswith("-"):
                # Handle built-in help options
                if a in ["--help", "-h"]:
                    print(invoker.command.format_help())
                    raise Exit(0)
                if a.startswith("--") and '=' in a:
                    # --long-format=value
                    a, val = a.split('=', 1)
                    args.insert_front(val)

                invoker.eat_options(a, args)
            elif isinstance(invoker.command, Group):
                invoker = invoker.sub_command(a)
            else:
                invoker.eat_arg(a)

        r = invoker.invoke()
        if r is None:
            r = 0  # if no return value is provided, assume success

        if isinstance(invoker.command, Group):
            # group invoked without sub-command. we want to deal with this after `invoker.invoke()`
            # to give the parent command callbacks the opportunity to execute.
            click.secho("Command is missing", fg='red', err=True)
            print(invoker.command.format_help())
            raise Exit(1)

        return r

    def main(self, args=sys.argv[1:], prog_name=None):
        '''
        Use this Command as the main entry point for a script.

        prog_name parameter is a hack to reuse click.CliRunner
        '''
        try:
            self(*args)
            sys.exit(0)
        except Exit as e:
            sys.exit(e.code)
        except BadCmdLineException as e:
            click.secho(str(e), fg='red', err=True)
            sys.exit(1)

    def check_consistency(self):
        """
        Validate that the command configuration is consistent and well-formed.
        Raises BadConfigException if any issues are found.
        """

        # Get function signature for parameter analysis
        sig = inspect.signature(self.callback)
        func_params = list(sig.parameters.keys())

        # For Group sub-commands, first parameter is context from parent
        # For regular commands, all parameters should be covered by decorators
        context_param_offset = 1 if self.parent is not None else 0
        expected_func_params = func_params[context_param_offset:]

        def error(msg: str) -> BadConfigException:
            return BadConfigException(
                f"{msg} in function '{self.callback.__name__}' signature: "
                f"{inspect.getsourcefile(self.callback)}:{inspect.getsourcelines(self.callback)[1]}")

        # Check for missing function parameters
        for p in self.options:
            if p.name not in func_params:
                raise error(f"@option names '{p.name}' but no such parameter exists")

        for a in self.arguments:
            if a.name not in func_params:
                raise error(f"@argument names '{a.name}' but no such parameter exists")

        # Collect all parameter names from decorators
        decorator_param_names = set()
        for p in self.options + self.arguments:
            if p.name in decorator_param_names:
                raise error(f"Duplicate parameter name '{p.name}' found in command '{self.name}' decorators")
            decorator_param_names.add(p.name)

        # Check boolean option conflicts
        for p in self.options:
            if p.type == bool:
                if p.required:
                    raise error(f"It makes no sense to require a boolean option '{p.name}'")

        # Check for required parameter with default value
        for p in self.options + self.arguments:
            if p.required and p.default != NO_DEFAULT:
                raise error(f"'{p.name}' is marked as required but with default value '{p.default}'")

        # Check for uncovered function parameters
        for p in expected_func_params:
            if p not in decorator_param_names:
                raise error(f"Function parameter '{p}' is not covered by any @option or @argument decorator")

        # Type system checks
        for p in self.options + self.arguments:
            fp = sig.parameters[p.name]

            # Check if multiple=True is used correctly with List type
            if p.multiple:
                t = normalize_type(to_type(fp))
                if t is None:
                    raise error(f"Parameter '{p.name}' with multiple=True requires a type annotation")
                if not (hasattr(t, '__origin__') and t.__origin__ is list):
                    raise error(f"Parameter '{p.name}' with multiple=True requires a List[T]")

            # similarly, if type is List, must be multiple=True
            t = to_type(fp)
            if hasattr(t, '__origin__') and t.__origin__ is list and not p.multiple:
                raise error(f"Parameter '{p.name}' is typed as List but missing multiple=True")

            # Check default value type compatibility
            if p.default != NO_DEFAULT and not isinstance(p.default, p.type):
                raise error(
                    f"Default value '{p.default}' for parameter '{p.name}' is incompatible with type '{p.type.__name__}'")

            if not p.required and p.default == NO_DEFAULT and fp.default == inspect.Parameter.empty:
                if p.type != bool:  # boolean parameters get implicit default value of False
                    raise error(f"Parameter '{p.name}' is optional but has no default value")

        # Check for duplicate option names
        all_option_names = set()
        for p in self.options:
            for name in p.option_names:
                if name in all_option_names:
                    raise error(f"Duplicate option name '{name}' found")
                all_option_names.add(name)

        # Check option name formats
        for p in self.options:
            for opt_name in p.option_names:
                if not re.match(r'^-[a-zA-Z]$|^--[a-zA-Z][-a-zA-Z0-9]*$', opt_name):
                    raise error(f"Invalid option name '{opt_name}'")

        # Check argument ordering (required after optional)
        found_optional = False
        for a in self.arguments:
            if not a.required:
                found_optional = True
            elif found_optional:
                raise error(f"Required argument '{a.name}' cannot appear after optional arguments")

        # Check multiple arguments placement and count
        multiple_args = [arg.name for arg in self.arguments if arg.multiple]
        if len(multiple_args) > 1:
            raise error(f"Cannot have more than one multiple=True argument, found: {multiple_args}")

        if len(multiple_args) == 1:
            # multiple=True argument must be the last argument
            if self.arguments and self.arguments[-1].name != multiple_args[0]:
                raise error(f"Argument '{multiple_args[0]}' with multiple=True must be the last argument")

        # Group-specific checks
        if isinstance(self, Group):
            # Group can have up to one argument can be used to capture sub-command
            if len(self.arguments) > 1:
                raise error(f"Group command '{self.name}' can have at most one argument to capture sub-command name")

            # Check for empty groups (only if this is a Group)
            if not self.commands:
                raise error(f"Group command '{self.name}' has no subcommands defined")

            # Check subcommand name conflicts
            subcommand_names = [cmd.name for cmd in self.commands]
            if len(subcommand_names) != len(set(subcommand_names)):
                duplicates = [name for name in set(subcommand_names) if subcommand_names.count(name) > 1]
                raise error(f"Duplicate subcommand names found in group '{self.name}': {duplicates}")

            # Recursively check subcommands for Groups
            for c in self.commands:
                c.check_consistency()

    def _usage_line(self, program_name) -> str:
        parts = ["Usage:"]

        # Program name
        parts.append(program_name)

        # Build command path (for subcommands)
        command_path: List[str] = []
        current = self
        while current.parent is not None:
            command_path.insert(0, current.name)
            current = current.parent
        if len(command_path) > 0:
            parts.append(" ".join(command_path))

        # Add options placeholder if we have options
        if self.options:
            parts.append("[OPTIONS]")

        # Add arguments
        for a in self.arguments:
            if a.required:
                if a.multiple:
                    parts.append(f"<{a.metavar}>...")
                else:
                    parts.append(f"<{a.metavar}>")
            else:
                if a.multiple:
                    parts.append(f"[{a.metavar}...]")
                else:
                    parts.append(f"[{a.metavar}]")
        if isinstance(self, Group):
            if len(self.arguments) == 0:
                # Add subcommand placeholder for groups
                parts.append("COMMAND")
            parts.append("...")

        return " ".join(parts)

    def format_help(self, program_name: str = os.path.basename(sys.argv[0])) -> str:
        """
        Generate and return a formatted help message for this command.

        :param program_name
            Name of the program to display in the usage line. Defaults to the name of the running script.
        """

        lines = [self._usage_line(program_name)]

        # Description from docstring
        if self.callback.__doc__:
            lines.append("")
            # Clean up the docstring - remove leading/trailing whitespace and dedent
            doc_lines = self.callback.__doc__.strip().split('\n')
            # Remove common leading whitespace
            import textwrap
            description = textwrap.dedent('\n'.join(doc_lines)).strip()
            lines.append(description)

        # Arguments section
        if self.arguments:
            lines.append("")
            lines.append("Arguments:")
            for arg in self.arguments:
                arg_line = f"  {arg.metavar}"

                # Add type info
                if arg.type != str:
                    type_name = getattr(arg.type, '__name__', str(arg.type))
                    arg_line += f" ({type_name})"

                # Add required/optional indicator and default
                if not arg.required:
                    if arg.default != NO_DEFAULT:
                        arg_line += f" [default: {arg.default}]"
                    else:
                        arg_line += " [optional]"
                # Add multiple indicator
                if arg.multiple:
                    arg_line += " (multiple)"
                lines.append(arg_line)

                # Add help text if available
                if arg.help:
                    help_lines = arg.help.strip().split('\n')
                    for help_line in help_lines:
                        lines.append(f"      {help_line}")

        # Options section
        self._format_options("Options", lines)

        # Commands section (for Groups)
        if isinstance(self, Group) and self.commands:
            lines.append("")
            lines.append("Commands:")
            for cmd in self.commands:
                cmd_line = f"  {cmd.name}"
                lines.append(cmd_line)

                # Add command description from docstring
                if cmd.callback.__doc__:
                    # Get first line of docstring as brief description
                    first_line = cmd.callback.__doc__.strip().split('\n')[0]
                    lines.append(f"      {first_line}")

        return '\n'.join(lines)

    def _format_options(self, caption: str, lines: list[str]):
        options = [opt for opt in self.options if not opt.hidden]
        if options:
            lines.append("")
            lines.append(f"{caption}:")
            for opt in options:
                # Format option names
                opt_names = ", ".join(opt.option_names)
                opt_line = f"  {opt_names}"

                # Add metavar for non-boolean options
                if opt.type == bool:
                    pass
                elif opt.metavar:
                    opt_line += f" {opt.metavar}"
                else:
                    type_name = getattr(opt.type, '__name__', str(opt.type))
                    opt_line += f" {type_name.upper()}"

                lines.append(opt_line)

                # Add description line with help and metadata
                desc_parts = []
                if opt.help:
                    desc_parts.append(opt.help)

                # Add default value info
                if opt.default != NO_DEFAULT and opt.type != bool:
                    desc_parts.append(f"[default: {opt.default}]")
                elif not opt.required and opt.type != bool:
                    desc_parts.append("[optional]")

                # Add required indicator
                if opt.required:
                    desc_parts.append("[required]")

                # Add multiple indicator
                if opt.multiple:
                    desc_parts.append("(multiple)")

                if desc_parts:
                    lines.append(f"      {' '.join(desc_parts)}")

        if self.parent:
            self.parent._format_options(f"Options (common to {self.parent.name})", lines)

    def format_asciidoc_table(self, program_name: str) -> str:
        """
        Generate an AsciiDoc table for the command's options and arguments.
        Returns the table as a string.
        """
        lines = [f"`{self._usage_line(program_name)}`", ""]

        def _print_required(p: Parameter) -> str:
            return "Yes" if p.required else "No"

        if self.arguments:
            lines.append("[cols=\"2,4,1\"]")
            lines.append("|===")
            lines.append("|Argument |Description |Required")
            lines.append("")

            for arg in self.arguments:
                def _print_name() -> str:
                    if arg.multiple:
                        return f"`<{arg.metavar}>...`"
                    else:
                        return f"`<{arg.metavar}>`"

                def _print_description() -> str:
                    desc_parts = []
                    if arg.help:
                        desc_parts.append(arg.help)

                    if arg.type != str:
                        type_name = getattr(arg.type, '__name__', str(arg.type))
                        desc_parts.append(f"(type: {type_name})")

                    if arg.default != NO_DEFAULT:
                        desc_parts.append(f"Default: `{arg.default}`")

                    return " ".join(desc_parts)

                lines.append("// GENERATED. MODIFY IN CLI SOURCE CODE")
                lines.append(f"|{_print_name()}")
                lines.append(f"|{_print_description()}")
                lines.append(f"|{_print_required(arg)}")
                lines.append("")

            lines.append("|===")

        if self.options:
            lines.append("[cols=\"2,4,1\"]")
            lines.append("|===")
            lines.append("|Option |Description |Required")
            lines.append("")

            for opt in sorted([opt for opt in self.options if not opt.hidden], key=lambda o: o.name):
                def _print_name() -> str:
                    names = ", ".join([f"`{name}`" for name in opt.option_names])

                    # Add metavar for non-boolean options
                    if opt.type != bool:
                        if opt.metavar:
                            names += f" {opt.metavar}"
                        else:
                            type_name = getattr(opt.type, '__name__', str(opt.type))
                            names += f" {type_name.upper()}"

                    return names

                def _print_description() -> str:
                    desc_parts = []
                    if opt.help:
                        desc_parts.append(opt.help)

                    if opt.default != NO_DEFAULT and opt.type != bool:
                        desc_parts.append(f"Default: `{opt.default}`")

                    if opt.multiple:
                        desc_parts.append("(can be specified multiple times)")

                    return " ".join(desc_parts)

                lines.append("// GENERATED. MODIFY IN CLI SOURCE CODE")
                lines.append(f"|{_print_name()}")
                lines.append(f"|{_print_description()}")
                lines.append(f"|{_print_required(opt)}")
                lines.append("")

            lines.append("|===")

        return "\n".join(lines)

    def __repr__(self):
        return f"<Command name={self.name!r} options={self.options!r} arguments={self.arguments!r}>"


class Group(Command):
    '''
    Special type of command that has sub-commands, e.g. 'git commit', 'git push', where 'git' is a group command.

    A sub-command receives the return value of its parent command as the first argument to its callback function,
    which is how we expect the parent to pass the context to the child.
    '''
    commands: List[Command]

    def __init__(self, callback: Callable, name: str | None = None, help: str | None = None, params: Sequence[Parameter] = ()):
        super().__init__(callback, name, help, params)
        self.commands = []

    def add_command(self, c: Command):
        self.commands.append(c)
        if c.parent is not None:
            raise BadConfigException(f"Command '{c.name}' is already a sub-command of '{c.parent.name}'")
        c.parent = self

    @decorator
    def command(self, name: Optional[str] = None, help: Optional[str] = None) -> Callable[..., Command]:
        from .decorators import _command

        def decorator(f: Callable) -> Command:
            c = _command(name, help, Command)(f)
            self.add_command(c)
            return c
        return decorator

    @decorator
    def group(self, name: Optional[str] = None, help: Optional[str] = None) -> Callable[..., Group]:
        from .decorators import _command

        def decorator(f: Callable) -> Group:
            g = _command(name, help, Group)(f)
            self.add_command(g)
            return g
        return decorator

    def find_subcommand(self, name: str) -> Command:
        for c in self.commands:
            if c.name == name:
                return c
        msg = f"Unknown command: {name}"
        maybe = _maybe(name, [c.name for c in self.commands])
        if maybe:
            msg += f" (did you mean '{maybe}'?)"
        raise BadCmdLineException(msg)


class ArgList:
    '''
    This class represents a list of arguments, and provides methods to consume arguments from the front of the list
    '''
    args: list[str]

    def __init__(self, args: list[str]):
        self.args = args

    def peek(self, caller: Any) -> str:
        if len(self.args) == 0:
            raise BadCmdLineException(f"{caller} is missing an argument")
        return self.args[0]

    def eat(self, caller: Any) -> str:
        if len(self.args) == 0:
            raise BadCmdLineException(f"{caller} is missing an argument")
        return self.args.pop(0)

    def has_more(self) -> bool:
        return len(self.args) > 0

    def insert_front(self, arg):
        self.args.insert(0, arg)


class _Invoker:
    '''
    This class builds up data needed to invoke a command
    '''
    command: Command
    parent: _Invoker | None = None
    kwargs: dict[str, Any]

    nargs = 0  # number of arguments consumed, used to identify the processor of the next argument

    def __init__(self, command: Command):
        self.command = command
        self.kwargs = {}

    def eat_arg(self, arg: str):
        l = self.command.arguments

        if self.nargs < len(l):
            a = l[self.nargs]
        else:
            if len(l) > 0 and l[-1].multiple:
                a = l[-1]
            else:
                raise BadCmdLineException(f"Too many arguments for '{self.command.name}' command: {arg}")

        self.kwargs[a.name] = a.append(self.kwargs.get(a.name), arg)
        self.nargs += 1

    def eat_options(self, option_name: str, args: ArgList):
        inv: _Invoker | None = self
        option_names = []
        while inv is not None:
            for o in inv.command.options:
                if option_name in o.option_names:
                    inv.kwargs[o.name] = o.append(inv.kwargs.get(o.name), option_name, args)
                    return
                else:
                    option_names += o.option_names
            inv = inv.parent

        msg = f"No such option '{option_name}' for '{self.command.name}' command"
        maybe = _maybe(option_name, option_names)
        if maybe:
            msg += f" (did you mean '{maybe}'?)"
        raise BadCmdLineException(msg)

    def sub_command(self, name: str) -> _Invoker:
        c = cast(Group, self.command).find_subcommand(name)
        i = _Invoker(c)
        i.parent = self
        if len(self.command.arguments) > 0:
            self.eat_arg(name)      # this allows the group to see the selected sub-command as an argument
        return i

    def invoke(self) -> Any:
        '''
        Invoke the user defined methods with the right parameter bindings from options and arguments,
        then return what the function returned
        '''

        # fill in default values
        for a in self.command.arguments:
            if a.name not in self.kwargs:
                if a.required:
                    raise BadCmdLineException(f"Missing required argument '{a.name}' for command '{self.command.name}'")
                if a.default != NO_DEFAULT:
                    self.kwargs[a.name] = a.default

        for o in self.command.options:
            if o.name not in self.kwargs:
                if o.required:
                    raise BadCmdLineException(f"Missing required option '{o.option_names[0]}' for command '{self.command.name}'")
                if o.default != NO_DEFAULT:
                    self.kwargs[o.name] = o.default

        if self.parent is not None:
            return self.command.callback(self.parent.invoke(), **self.kwargs)
        else:
            return self.command.callback(**self.kwargs)


def _maybe(given: str, candidates: Sequence[str]) -> Optional[str]:
    '''
    Typo recovery suggestion. Find the best match from the given candidates,
    but only if it's close enough.
    '''

    if len(candidates) == 0:
        return None  # min() doesn't work if arg is empty

    c = min(candidates, key=lambda c: edit_distance(given, c))
    if edit_distance(c, given) <= 4:
        return c
    else:
        return None
