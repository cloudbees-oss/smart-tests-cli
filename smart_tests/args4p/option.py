from typing import Any, Callable, Optional

from .exceptions import BadCmdLineException
from .parameter import Parameter, normalize_type


class NoDefault:
    '''
    If there's no default value configured for option/argument, we use `NO_DEFAULT`.
    In contrast, `None` is a valid and very typical default value.
    '''
    pass


NO_DEFAULT = NoDefault()


class Option(Parameter):
    clazz = "option"

    hidden: bool

    def __init__(
            self, name: Optional[str],
            option_names: list[str],
            help: str | None = None,
            type: type | Callable[..., Any] | None = str,
            default: Any = NO_DEFAULT,
            required: bool = False,
            metavar: str | None = None,
            multiple: bool = False,
            hidden: bool = False,
            optional_value: bool = False,
            flag_value: Any = None):
        self.name = name        # type: ignore[assignment]  # once properly constructed, name is never None
        self.option_names = option_names
        self.help = help
        self.type = normalize_type(type)
        self.default = default
        self.required = required
        self.metavar = metavar
        self.multiple = multiple
        self.hidden = hidden
        # When True, the value is taken ONLY from an inline `--opt=value` form; a bare `--opt`
        # (no `=`) binds `flag_value` instead of consuming the following argument. This lets a
        # single option behave both as a flag (`--opt`) and as a valued option (`--opt=value`).
        self.optional_value = optional_value
        self.flag_value = flag_value

    # 'args' is ArgList, but typing it creates a circular import
    def append(self, existing: Any, option_name: str, args, has_inline: bool = False):
        '''
        Given the current value 'existing' that represents the present value to invoke the user function with,
        this method is called when this option was specified as 'option_name' on the command line.
        'args' is pointing at the next argument after 'option_name', which may be the value for this option.
        'has_inline' is True when the option was given as `--opt=value` (the value has been pushed to
        the front of 'args' by the parser).
        '''

        if self.optional_value:
            if has_inline:
                v = args.eat(option_name)
                try:
                    v = self.type(v)
                except ValueError as e:
                    raise BadCmdLineException(f"Invalid value '{v}' for option '{option_name}': {str(e)}") from e
            else:
                # bare `--opt`: bind the configured flag value, do NOT consume the next argument.
                v = self.flag_value
        elif self.type == bool or self.type == Optional[bool]:
            v = True
        else:
            v = args.eat(option_name)
            try:
                v = self.type(v)
            except ValueError as e:
                raise BadCmdLineException(f"Invalid value '{v}' for option '{option_name}': {str(e)}") from e

        if self.multiple:
            if existing is None:
                existing = []
            existing.append(v)
            return existing
        else:
            return v

    def attach_to_command(self, command):  # typing command makes reference circular
        super().attach_to_command(command)

        if self.metavar is None:
            def type_name(t):
                if hasattr(t, "__name__"):
                    return t.__name__
                else:
                    return str(t)
            self.metavar = type_name(self.type).upper()
        if self.type == bool and self.default is NO_DEFAULT:
            # if the flag is absent, bind the value to False, or else the function signature requires a defalut value,
            # which is silly
            self.default = False

    def __repr__(self):
        return (f"Option(name={self.name!r}, option_names={self.option_names!r}, help={self.help!r}, "
                f"type={self.type.__name__!r}, default={self.default!r}, required={self.required!r}, "
                f"metavar={self.metavar!r}, many={self.multiple!r})")
