import datetime
import re
import sys

import dateutil.parser
from dateutil.tz import tzlocal

from smart_tests.args4p.exceptions import BadCmdLineException


class Percentage:
    def __init__(self, value: float):
        self.value = value

    def __str__(self):
        return f"{self.value * 100}%"

    def __float__(self):
        return self.value


def parse_percentage(value: str) -> Percentage:
    try:
        missing_percent = False
        if value.endswith('%'):
            x = float(value[:-1]) / 100
            if 0 <= x <= 1:
                return Percentage(x)
        else:
            missing_percent = True
    except ValueError:
        pass

    msg = "Expected percentage like 50% but got '{}'".format(value)
    if missing_percent and sys.platform.startswith("win"):
        msg += " ('%' is a special character in batch files, so please write '50%%' to pass in '50%')"
    raise BadCmdLineException(msg)


class Duration:
    def __init__(self, seconds: float):
        self.seconds = seconds

    def __str__(self):
        return f"{self.seconds}s"

    def __float__(self):
        return self.seconds


def parse_duration(value: str) -> Duration:
    try:
        return Duration(convert_to_seconds(value))
    except ValueError:
        raise BadCmdLineException("Expected duration like 3600, 30m, 1h15m but got '{}'".format(value))


class KeyValue:
    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

    def __str__(self):
        return f"{self.key}={self.value}"

    def __iter__(self):
        return iter((self.key, self.value))

    def __getitem__(self, index):
        return (self.key, self.value)[index]


def parse_key_value(value: str) -> KeyValue:
    """
    Handles options that take key/value pairs.

    The preferred syntax is "--option key=value" and that's what we should be advertising in docs and help,
    but for compatibility (?) we accept "--option key:value"

    Typically, this is used with multiple=True to produce `Sequence[Tuple[str, str]]`.
    """
    error_message = "Expected a key-value pair formatted as --option key=value, but got '{}'"

    for delimiter in ['=', ':']:
        if delimiter in value:
            kv = value.split(delimiter, 1)
            if len(kv) != 2:
                raise BadCmdLineException(error_message.format(value))
            return KeyValue(kv[0].strip(), kv[1].strip())

    raise BadCmdLineException(error_message.format(value))


class Fraction:
    def __init__(self, numerator: int, denominator: int):
        self.numerator = numerator
        self.denominator = denominator

    def __str__(self):
        return f"{self.numerator}/{self.denominator}"

    def __iter__(self):
        return iter((self.numerator, self.denominator))

    def __getitem__(self, index):
        return (self.numerator, self.denominator)[index]

    def __float__(self):
        return self.numerator / self.denominator


def parse_fraction(value: str) -> Fraction:
    try:
        v = value.strip().split('/')
        if len(v) == 2:
            n = int(v[0])
            d = int(v[1])
            return Fraction(n, d)
    except ValueError:
        pass

    raise BadCmdLineException("Expected fraction like 1/2 but got '{}'".format(value))


class DateTimeWithTimezone:
    def __init__(self, dt: datetime.datetime):
        self.dt = dt

    def __str__(self):
        return self.dt.isoformat()

    def datetime(self):
        return self.dt


def parse_datetime_with_timezone(value: str) -> DateTimeWithTimezone:
    try:
        dt = dateutil.parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tzlocal())
        return DateTimeWithTimezone(dt)
    except ValueError:
        raise BadCmdLineException("Expected datetime like 2023-10-01T12:00:00 but got '{}'".format(value))


def convert_to_seconds(s: str) -> float:
    """Convert duration string to seconds"""
    units = {'s': 1, 'm': 60, 'h': 60 * 60, 'd': 60 * 60 * 24, 'w': 60 * 60 * 24 * 7}

    if s.isdigit():
        return float(s)

    duration = 0
    for m in re.finditer(r'(?P<val>\d+)(?P<unit>[smhdw]?)', s, flags=re.I):
        val = m.group('val')
        unit = m.group('unit')

        if val is None or unit is None:
            raise ValueError(f"unable to parse: {s}")

        u = units.get(unit)
        if u is None:
            raise ValueError(f"unable to parse: {s}")

        duration += int(val) * u

    return float(duration)


# Can the output deal with Unicode emojis?
try:
    '\U0001f389'.encode(sys.stdout.encoding or "ascii")
    # If stdout encoding is unavailable, such as in case of pipe, err on the safe side (EMOJI=False)
    # This is a judgement call, but given that emojis do not serve functional purposes and purely decorative
    # erring on the safe side seems like a reasonable call.
    EMOJI = True
except UnicodeEncodeError:
    EMOJI = False


def emoji(s: str, fallback: str = '') -> str:
    """
    Used to safely use Emoji where we can.

    Returns 's' in an environment where stdout can deal with emojis, but 'fallback' otherwise.
    """
    return s if EMOJI else fallback


def ignorable_error(e: Exception) -> str:
    return "An error occurred on Smart Tests CLI. You can ignore this message since the process will continue. " \
           f"Error: {e}"


def parse_key_value_list(values: list) -> list:
    """Parse a list of key-value strings into KeyValue objects"""
    return [parse_key_value(v) for v in values]


# Backward compatibility functions for existing usage
def validate_key_value(value: str):
    """Validate and parse a key-value string, returning a tuple for backward compatibility"""
    kv = parse_key_value(value)
    return (kv.key, kv.value)


def validate_datetime_with_tz(value: str):
    """Validate and parse a datetime string, returning a datetime object for backward compatibility"""
    dt_obj = parse_datetime_with_timezone(value)
    return dt_obj.dt


def validate_past_datetime(dt_value: datetime.datetime):
    """Validate that the provided datetime is in the past"""
    if dt_value is None:
        return dt_value

    if not isinstance(dt_value, datetime.datetime):
        raise BadCmdLineException("Expected a datetime object.")

    now = datetime.datetime.now(tz=tzlocal())
    if dt_value > now:
        raise BadCmdLineException("The provided timestamp must be in the past.")

    return dt_value


def _key_value_compat(value: str):
    """Compatibility wrapper that returns tuple instead of KeyValue object"""
    kv = parse_key_value(value)
    return (kv.key, kv.value)


def _datetime_with_tz_compat(value: str):
    """Compatibility wrapper that returns datetime instead of DateTimeWithTimezone object"""
    dt_obj = parse_datetime_with_timezone(value)
    return dt_obj.dt


def validate_iso_week(value: str) -> str:
    """Validate ISO week format YYYY-Www and week number range (01-53)"""
    pattern = r'^\d{4}-W\d{2}$'
    if not re.match(pattern, value):
        raise BadCmdLineException(
            f"Invalid year-week format: '{value}'. Expected format: YYYY-Www (e.g., 2026-W15)"
        )

    week_num = int(value.split('-W')[1])
    if week_num < 1 or week_num > 53:
        raise BadCmdLineException(
            f"Invalid week number: '{value}'. Week must be between 01 and 53"
        )

    return value


KEY_VALUE = _key_value_compat
DATETIME_WITH_TZ = _datetime_with_tz_compat
