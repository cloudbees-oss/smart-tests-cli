# This package defines Typer-style annotation based option/command declarations
from typing import Any, Callable

from ..argument import Argument as _Argument
from ..option import NO_DEFAULT
from ..option import Option as _Option


def Option(
        *option_names: str,
        help: str | None = None, type: type | Callable | None = None, default: Any = NO_DEFAULT, required: bool = False,
        metavar: str | None = None, multiple: bool = False, hidden: bool = False
) -> _Option:
    '''
    See README.md for usage
    '''

    return _Option(name=None, option_names=list(option_names), help=help, type=type,
                   default=default, required=required, metavar=metavar, multiple=multiple, hidden=hidden)


def Argument(
        type: type | Callable = str,
        multiple: bool = False,
        required: bool = True,
        metavar: str | None = None,
        help: str | None = None,
        default: Any = NO_DEFAULT
) -> _Argument:
    '''
    See README.md for usage
    '''
    return _Argument(name=None, type=type, multiple=multiple, required=required, metavar=metavar, help=help, default=default)


class Exit(BaseException):
    '''
    Raise this exception to exit the CLI with the given exit code.
    Extends BaseException (not Exception) so that broad `except Exception` handlers in user code
    do not accidentally swallow it — analogous to Java's Error vs Exception distinction.
    '''

    def __init__(self, code: int):
        self.code = code
