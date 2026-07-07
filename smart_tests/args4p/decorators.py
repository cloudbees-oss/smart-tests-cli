from __future__ import annotations

from typing import Any, Callable, Optional, Type

from . import decorator
from .argument import Argument
from .command import Command, Group
from .exceptions import BadConfigException
from .option import NO_DEFAULT, Option
from .parameter import Parameter


def _command(
        name: Optional[str] = None,
        help: Optional[str] = None,
        cls: Type[Command] = Command,
):
    def decorator(f: Callable) -> Command:
        return cls(name=name, help=help, callback=f)

    return decorator


@decorator
def command(name: Optional[str] = None, help: Optional[str] = None) -> Callable[..., Command]:
    return _command(name, help, Command)


@decorator
def group(name: Optional[str] = None, help: Optional[str] = None) -> Callable[..., Group]:
    return _command(name, help, Group)  # type: ignore


@decorator
def option(
        *param_decls: str,
        help: str | None = None, type: type | Callable | None = None, default: Any = NO_DEFAULT, required: bool = False,
        metavar: str | None = None, multiple: bool = False, hidden: bool = False
) -> Callable:
    '''
    See README.md for usage
    '''

    def decorator(f: Callable) -> Callable:
        if len(param_decls) == 0:
            raise BadConfigException("Variable name is required")

        variable_name = param_decls[-1]
        if len(param_decls) == 1:
            option_names = [f"--{variable_name.replace('_', '-')}"]
        else:
            option_names = list(param_decls[:-1])

        o = Option(
            name=variable_name,
            option_names=option_names,
            help=help,
            type=type,
            default=default,
            required=required,
            metavar=metavar,
            multiple=multiple,
            hidden=hidden)

        return _attach(f, o)

    return decorator


@decorator
def argument(
    name: str,
    type: type | Callable = str,
    multiple: bool = False,
    required: bool = True,
    metavar: str | None = None,
    help: str | None = None,
    default: Any = NO_DEFAULT
) -> Callable:
    '''
    See README.md for usage
    '''
    a = Argument(name=name, type=type, multiple=multiple, required=required, metavar=metavar, help=help, default=default)
    return lambda f: _attach(f, a)


def _attach(f: Callable[..., Any], param: Parameter):
    # depending on whether a command annotation comes before/after parameter annotations, 'f' might be
    # a naked user-defined function or a Command instance
    if isinstance(f, Command):
        f.add_param(param, True)
    else:
        if not hasattr(f, "__args4p_params__"):
            f.__args4p_params__ = []  # type: ignore

        f.__args4p_params__.append(param)  # type: ignore

    return f
