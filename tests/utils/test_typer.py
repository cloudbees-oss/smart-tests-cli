import datetime
from datetime import timezone
from unittest import TestCase

import typer
from dateutil.tz import tzlocal

from launchable.utils.typer_types import (DATETIME_WITH_TZ, KEY_VALUE, convert_to_seconds,
                                          validate_datetime_with_tz, validate_key_value)


class DurationTypeTest(TestCase):
    def test_convert_to_seconds(self):
        self.assertEqual(convert_to_seconds('30s'), 30)
        self.assertEqual(convert_to_seconds('5m'), 300)
        self.assertEqual(convert_to_seconds('1h30m'), 5400)
        self.assertEqual(convert_to_seconds('1d10h15m'), 123300)
        self.assertEqual(convert_to_seconds('15m 1d 10h'), 123300)

        with self.assertRaises(ValueError):
            convert_to_seconds('1h30k')


class KeyValueTypeTest(TestCase):
    def test_conversion(self):
        # Test the validate_key_value function directly
        self.assertEqual(validate_key_value('bar=zot'), ('bar', 'zot'))
        self.assertEqual(validate_key_value('a=b'), ('a', 'b'))
        self.assertEqual(validate_key_value('key:value'), ('key', 'value'))

        with self.assertRaises(typer.BadParameter):
            validate_key_value('invalid')

        # Test the parser class
        parser = KEY_VALUE
        self.assertEqual(parser('bar=zot'), ('bar', 'zot'))
        self.assertEqual(parser('a=b'), ('a', 'b'))


class TimestampTypeTest(TestCase):
    def test_conversion(self):
        # Test the validate_datetime_with_tz function directly
        result1 = validate_datetime_with_tz('2023-10-01 12:00:00')
        expected1 = datetime.datetime(2023, 10, 1, 12, 0, 0, tzinfo=tzlocal())
        self.assertEqual(result1, expected1)

        result2 = validate_datetime_with_tz('2023-10-01 20:00:00+00:00')
        expected2 = datetime.datetime(2023, 10, 1, 20, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(result2, expected2)

        result3 = validate_datetime_with_tz('2023-10-01T20:00:00Z')
        expected3 = datetime.datetime(2023, 10, 1, 20, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(result3, expected3)

        # Test the parser class
        parser = DATETIME_WITH_TZ
        result4 = parser('2023-10-01 12:00:00')
        expected4 = datetime.datetime(2023, 10, 1, 12, 0, 0, tzinfo=tzlocal())
        self.assertEqual(result4, expected4)
