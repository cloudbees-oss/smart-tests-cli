import datetime
import sys
from datetime import timezone
from unittest import TestCase

import typer
from dateutil.tz import tzlocal

from smart_tests.utils.typer_types import (DATETIME_WITH_TZ, EMOJI, KEY_VALUE, DateTimeWithTimezone, Duration, Fraction,
                                           KeyValue, Percentage, convert_to_seconds, emoji, parse_datetime_with_timezone,
                                           parse_duration, parse_fraction, parse_key_value, parse_percentage,
                                           validate_datetime_with_tz, validate_key_value, validate_past_datetime)


class PercentageTest(TestCase):
    def test_parse_valid_percentage(self):
        pct = parse_percentage("50%")
        self.assertIsInstance(pct, Percentage)
        self.assertEqual(pct.value, 0.5)
        self.assertEqual(float(pct), 0.5)
        self.assertEqual(str(pct), "50.0%")

    def test_parse_edge_cases(self):
        # Test 0% and 100%
        self.assertEqual(parse_percentage("0%").value, 0.0)
        self.assertEqual(parse_percentage("100%").value, 1.0)

        # Test decimal percentages
        self.assertEqual(parse_percentage("25.5%").value, 0.255)

    def test_parse_invalid_percentage_missing_percent(self):
        orig_platform = sys.platform
        try:
            # Test Windows behavior
            sys.platform = "win32"
            with self.assertRaises(typer.BadParameter) as cm:
                parse_percentage("50")
            msg = str(cm.exception)
            self.assertIn("Expected percentage like 50% but got '50'", msg)
            self.assertIn("please write '50%%' to pass in '50%'", msg)

            # Test non-Windows behavior
            sys.platform = "linux"
            with self.assertRaises(typer.BadParameter) as cm:
                parse_percentage("50")
            msg = str(cm.exception)
            self.assertIn("Expected percentage like 50% but got '50'", msg)
            self.assertNotIn("please write '50%%' to pass in '50%'", msg)
        finally:
            sys.platform = orig_platform

    def test_parse_invalid_percentage_non_numeric(self):
        with self.assertRaises(typer.BadParameter) as cm:
            parse_percentage("abc%")
        msg = str(cm.exception)
        self.assertIn("Expected percentage like 50% but got 'abc%'", msg)

    def test_percentage_class_methods(self):
        pct = Percentage(0.75)
        self.assertEqual(str(pct), "75.0%")
        self.assertEqual(float(pct), 0.75)


class DurationTest(TestCase):
    def test_convert_to_seconds(self):
        self.assertEqual(convert_to_seconds('30s'), 30)
        self.assertEqual(convert_to_seconds('5m'), 300)
        self.assertEqual(convert_to_seconds('1h30m'), 5400)
        self.assertEqual(convert_to_seconds('1d10h15m'), 123300)
        self.assertEqual(convert_to_seconds('15m 1d 10h'), 123300)
        self.assertEqual(convert_to_seconds('1w'), 604800)  # 7 days

        # Test numeric only
        self.assertEqual(convert_to_seconds('3600'), 3600)

    def test_convert_to_seconds_invalid(self):
        with self.assertRaises(ValueError):
            convert_to_seconds('1h30k')

    def test_parse_duration(self):
        duration = parse_duration("30s")
        self.assertIsInstance(duration, Duration)
        self.assertEqual(duration.seconds, 30)
        self.assertEqual(float(duration), 30)
        self.assertEqual(str(duration), "30.0s")

    def test_parse_duration_invalid(self):
        # Note: convert_to_seconds returns 0.0 for invalid input instead of raising ValueError
        # So parse_duration returns Duration(0.0) for invalid input
        duration = parse_duration("invalid")
        self.assertEqual(duration.seconds, 0.0)


class KeyValueTest(TestCase):
    def test_parse_key_value_equals(self):
        kv = parse_key_value("key=value")
        self.assertIsInstance(kv, KeyValue)
        self.assertEqual(kv.key, "key")
        self.assertEqual(kv.value, "value")
        self.assertEqual(str(kv), "key=value")

        # Test tuple-like behavior
        self.assertEqual(kv[0], "key")
        self.assertEqual(kv[1], "value")
        self.assertEqual(list(kv), ["key", "value"])

    def test_parse_key_value_colon(self):
        kv = parse_key_value("key:value")
        self.assertEqual(kv.key, "key")
        self.assertEqual(kv.value, "value")

    def test_parse_key_value_with_spaces(self):
        kv = parse_key_value(" key = value ")
        self.assertEqual(kv.key, "key")
        self.assertEqual(kv.value, "value")

    def test_parse_key_value_with_multiple_delimiters(self):
        # Should split on first occurrence only
        kv = parse_key_value("key=value=extra")
        self.assertEqual(kv.key, "key")
        self.assertEqual(kv.value, "value=extra")

    def test_parse_key_value_invalid(self):
        with self.assertRaises(typer.BadParameter) as cm:
            parse_key_value("invalid")
        msg = str(cm.exception)
        self.assertIn("Expected a key-value pair formatted as --option key=value, but got 'invalid'", msg)

    def test_validate_key_value_compat(self):
        # Test backward compatibility function
        result = validate_key_value("key=value")
        self.assertEqual(result, ("key", "value"))

    def test_key_value_compat_function(self):
        # Test the KEY_VALUE constant
        result = KEY_VALUE("key=value")
        self.assertEqual(result, ("key", "value"))


class FractionTest(TestCase):
    def test_parse_fraction(self):
        frac = parse_fraction("3/4")
        self.assertIsInstance(frac, Fraction)
        self.assertEqual(frac.numerator, 3)
        self.assertEqual(frac.denominator, 4)
        self.assertEqual(str(frac), "3/4")
        self.assertEqual(float(frac), 0.75)

        # Test tuple-like behavior
        self.assertEqual(frac[0], 3)
        self.assertEqual(frac[1], 4)
        self.assertEqual(list(frac), [3, 4])

    def test_parse_fraction_with_spaces(self):
        frac = parse_fraction(" 1 / 2 ")
        self.assertEqual(frac.numerator, 1)
        self.assertEqual(frac.denominator, 2)

    def test_parse_fraction_invalid(self):
        with self.assertRaises(typer.BadParameter) as cm:
            parse_fraction("invalid")
        msg = str(cm.exception)
        self.assertIn("Expected fraction like 1/2 but got 'invalid'", msg)

    def test_parse_fraction_invalid_numbers(self):
        with self.assertRaises(typer.BadParameter):
            parse_fraction("a/b")


class DateTimeWithTimezoneTest(TestCase):
    def test_parse_datetime_with_timezone(self):
        dt_str = "2023-10-01 12:00:00+00:00"
        dt_obj = parse_datetime_with_timezone(dt_str)
        self.assertIsInstance(dt_obj, DateTimeWithTimezone)
        self.assertEqual(dt_obj.dt.year, 2023)
        self.assertEqual(dt_obj.dt.month, 10)
        self.assertEqual(dt_obj.dt.day, 1)
        self.assertEqual(dt_obj.dt.hour, 12)
        # dateutil.parser creates tzutc() which is equivalent to but not equal to timezone.utc
        self.assertEqual(dt_obj.dt.utcoffset(), timezone.utc.utcoffset(None))

    def test_parse_datetime_without_timezone(self):
        dt_str = "2023-10-01 12:00:00"
        dt_obj = parse_datetime_with_timezone(dt_str)
        self.assertEqual(dt_obj.dt.tzinfo, tzlocal())

    def test_parse_datetime_iso_format(self):
        dt_str = "2023-10-01T20:00:00Z"
        dt_obj = parse_datetime_with_timezone(dt_str)
        # dateutil.parser creates tzutc() which is equivalent to but not equal to timezone.utc
        self.assertEqual(dt_obj.dt.utcoffset(), timezone.utc.utcoffset(None))

    def test_parse_datetime_invalid(self):
        with self.assertRaises(typer.BadParameter) as cm:
            parse_datetime_with_timezone("invalid")
        msg = str(cm.exception)
        self.assertIn("Expected datetime like 2023-10-01T12:00:00 but got 'invalid'", msg)

    def test_datetime_with_timezone_methods(self):
        dt_obj = parse_datetime_with_timezone("2023-10-01T12:00:00Z")
        self.assertEqual(dt_obj.datetime(), dt_obj.dt)
        # Test string representation
        self.assertIn("2023-10-01T12:00:00", str(dt_obj))

    def test_validate_datetime_with_tz_compat(self):
        # Test backward compatibility function
        result = validate_datetime_with_tz("2023-10-01T12:00:00Z")
        self.assertIsInstance(result, datetime.datetime)
        # dateutil.parser creates tzutc() which is equivalent to but not equal to timezone.utc
        self.assertEqual(result.utcoffset(), timezone.utc.utcoffset(None))

    def test_datetime_with_tz_compat_function(self):
        # Test the DATETIME_WITH_TZ constant
        result = DATETIME_WITH_TZ("2023-10-01T12:00:00Z")
        self.assertIsInstance(result, datetime.datetime)

    def test_validate_past_datetime(self):
        # Test with None
        self.assertIsNone(validate_past_datetime(None))

        # Test with past datetime
        past_dt = datetime.datetime(2020, 1, 1, tzinfo=tzlocal())
        self.assertEqual(validate_past_datetime(past_dt), past_dt)

        # Test with future datetime
        future_dt = datetime.datetime(2030, 1, 1, tzinfo=tzlocal())
        with self.assertRaises(typer.BadParameter) as cm:
            validate_past_datetime(future_dt)
        msg = str(cm.exception)
        self.assertIn("The provided timestamp must be in the past", msg)

        # Test with non-datetime object
        with self.assertRaises(typer.BadParameter) as cm:
            validate_past_datetime("not a datetime")
        msg = str(cm.exception)
        self.assertIn("Expected a datetime object", msg)


class EmojiTest(TestCase):
    def test_emoji_function(self):
        # Test with fallback
        result = emoji("🎉", "!")
        self.assertIn(result, ["🎉", "!"])  # Depends on system capability

        # Test without fallback
        result = emoji("🎉")
        self.assertIn(result, ["🎉", ""])  # Depends on system capability

    def test_emoji_constant(self):
        # EMOJI should be a boolean
        self.assertIsInstance(EMOJI, bool)
