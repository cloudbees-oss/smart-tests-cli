from typing import Annotated, Optional
from unittest import TestCase

import smart_tests.args4p as args4p
from smart_tests.args4p import typer
from smart_tests.args4p.command import Command, _maybe
from smart_tests.args4p.exceptions import BadCmdLineException, BadConfigException


class CommandTest(TestCase):
    def test_invocation(self):
        @args4p.group()
        @args4p.option("--foo", "foo")
        def cli(foo: bool):
            self.assertTrue(foo)
            return "cli called"

        @cli.command()
        @args4p.option("--bar", "bar")
        def cmd1(parent_output: str, bar: int = 0):
            self.assertEqual(parent_output, "cli called")
            self.assertEqual(bar, 3)
            return "exit code"

        @cli.command()
        def cmd2():
            self.fail("Shouldn't be called")

        r = cli("cmd1", "--foo", "--bar", "3")
        self.assertEqual("exit code", r)

    def nested_sub_commands(self):
        @args4p.group()
        @args4p.option("foo")
        def grandpa(foo: bool):
            self.assertTrue(foo)
            return "grandpa"

        @grandpa.command()
        @args4p.option("bar")
        def daddy(parent_output: str, bar: int):
            self.assertEqual(parent_output, "grandpa")
            self.assertEqual(bar, 3)
            return "daddy"

        @daddy.command()
        @args4p.option("zot")
        def son(parent_output: str, zot: int):
            self.assertEqual(parent_output, "daddy")
            self.assertEqual(zot, 5)
            return "son"

        self.assertEqual("son", grandpa("daddy", "son", "--foo", "--bar", "3", "--zot", "5"))
        self.assertEqual("son", grandpa("--foo", "daddy", "--bar", "3", "son", "--zot", "5"))

    def test_option_default_value(self):
        v = None

        @args4p.command()
        @args4p.option("--foo", "foo", default=3)
        def cli(foo: int):
            nonlocal v
            v = foo

        cli()
        self.assertEqual(v, 3)

        cli("--foo", "5")
        self.assertEqual(v, 5)

    def test_command_with_arguments(self):
        """Test command with positional arguments"""
        received_args = []

        @args4p.command()
        @args4p.argument("name")
        @args4p.argument("count", type=int)
        def cmd_with_args(name: str, count: int):
            nonlocal received_args
            received_args = [name, count]

        cmd_with_args("test", "42")
        self.assertEqual(received_args, ["test", 42])

    def test_multiple_options(self):
        """Test command with multiple options"""
        captured = {}

        @args4p.command()
        @args4p.option("--name", "name", default="")
        @args4p.option("--count", "count", type=int, default=10)
        @args4p.option("--verbose", "verbose", type=bool)
        def multi_opt(name: str, count: int, verbose: bool):
            nonlocal captured
            captured = {"name": name, "count": count, "verbose": verbose}

        multi_opt("--name", "test", "--verbose")
        self.assertEqual(captured["name"], "test")
        self.assertEqual(captured["count"], 10)  # default value
        self.assertEqual(captured["verbose"], True)

    def test_required_option_missing(self):
        """Test that missing required options raise BadCmdLineException"""
        @args4p.command()
        @args4p.option("--required", "req", required=True)
        def cmd_req(req: str):
            pass

        with self.assertRaises(BadCmdLineException) as e:
            cmd_req()
        self.assertIn("Missing required option", str(e.exception))

    def test_too_many_arguments(self):
        """Test error when too many arguments are provided"""
        @args4p.command()
        @args4p.argument("name")
        def single_arg(name: str):
            pass

        with self.assertRaises(BadCmdLineException) as e:
            single_arg("arg1", "arg2")
        self.assertIn("Too many arguments", str(e.exception))
        self.assertIn("single-arg", str(e.exception))

    def test_missing_required_argument(self):
        """Test error when required argument is missing"""
        @args4p.command()
        @args4p.argument("name")
        def req_arg(name: str):
            pass

        with self.assertRaises(BadCmdLineException) as e:
            req_arg()
        self.assertIn("Missing required argument", str(e.exception))
        self.assertIn("'name'", str(e.exception))
        self.assertIn("command 'req-arg'", str(e.exception))

    def test_unknown_option(self):
        """Test error for unknown options"""
        @args4p.command()
        def no_opts():
            pass

        with self.assertRaises(BadCmdLineException) as e:
            no_opts("--unknown")
        self.assertIn("No such option", str(e.exception))
        self.assertIn("--unknown", str(e.exception))

    def test_unknown_subcommand(self):
        """Test error for unknown subcommands"""
        @args4p.group()
        def cli():
            pass

        @cli.command()
        def known(context):
            pass

        with self.assertRaises(BadCmdLineException) as e:
            cli("bogus")
        self.assertIn("Unknown command", str(e.exception))
        self.assertIn("bogus", str(e.exception))

    def test_multiple_values_option(self):
        """Test option that can accept multiple values"""
        collected = []

        @args4p.command()
        @args4p.option("--item", "items", multiple=True)
        def collect_items(items: list[str] = []):
            nonlocal collected
            collected = items or []

        collect_items("--item", "a", "--item", "b", "--item", "c")
        self.assertEqual(collected, ["a", "b", "c"])

    def test_multiple_values_argument(self):
        """Test argument that can accept multiple values"""
        collected = []

        @args4p.command()
        @args4p.argument("files", multiple=True)
        def process_files(files: list[str]):
            nonlocal collected
            collected = files or []

        process_files("file1.txt", "file2.txt", "file3.txt")
        self.assertEqual(collected, ["file1.txt", "file2.txt", "file3.txt"])

    def test_nested_groups(self):
        """Test nested command groups"""
        trace = []

        @args4p.group()
        def main():
            trace.append("main")

        @main.group()
        def sub(context):
            trace.append("sub")

        @sub.command()
        def leaf(context):
            trace.append("leaf")
            return "nested result"

        r = main("sub", "leaf")
        self.assertEqual(r, "nested result")
        self.assertEqual(trace, ["main", "sub", "leaf"])

    def test_option_inheritance(self):
        """Test that options are inherited from parent groups"""
        captured = {}

        @args4p.group()
        @args4p.option("--global", "global_opt")
        def main(global_opt: Optional[str] = None):
            captured["global"] = global_opt

        @main.command()
        @args4p.option("--local", "local_opt")
        def sub(context, local_opt: Optional[str] = None):
            captured["local"] = local_opt

        main("--global", "g_value", "sub", "--local", "l_value")
        self.assertEqual(captured["global"], "g_value")
        self.assertEqual(captured["local"], "l_value")

    def test_type_conversion(self):
        """Test automatic type conversion"""
        received = {}

        @args4p.command()
        @args4p.option("--count", "count", type=int)
        @args4p.option("--rate", "rate", type=float)
        @args4p.argument("name")
        def typed_cmd(name: str, count: int = 0, rate: float = 0):
            nonlocal received
            received = {"name": name, "count": count, "rate": rate}

        typed_cmd("test_name", "--count", "42", "--rate", "3.14")
        self.assertEqual(received["name"], "test_name")
        self.assertEqual(received["count"], 42)
        self.assertAlmostEqual(received["rate"], 3.14)

    def test_custom_command_name(self):
        """Test explicit command naming"""
        @args4p.group()
        def cli():
            pass

        @cli.command("custom-name")
        def some_function(context):
            return "custom command executed"

        # The command should be accessible by its custom name through the CLI object
        self.assertEqual(len(cli.commands), 1)
        self.assertEqual(cli.commands[0].name, "custom-name")
        self.assertEqual("custom command executed", cli("custom-name"))

    def test_boolean_flag_option(self):
        """Test boolean flag options"""
        received = {}

        @args4p.command()
        @args4p.option("--verbose", "verbose", type=bool)
        @args4p.option("--quiet", "quiet", type=bool, default=False)
        def flag_cmd(verbose: bool, quiet: bool):
            nonlocal received
            received = {"verbose": verbose, "quiet": quiet}

        # Test flag present
        flag_cmd("--verbose")
        self.assertTrue(received["verbose"])
        self.assertFalse(received["quiet"])

        # Reset
        received = {}

        # Test no flags
        flag_cmd()
        self.assertFalse(received["verbose"])
        self.assertFalse(received["quiet"])

    def test_bad_config_exception(self):
        """Test BadConfigException for invalid parameter configuration"""
        with self.assertRaises(BadConfigException):
            @args4p.command()
            @args4p.option("--test", "nonexistent_param")
            def bad_config(existing_param: str):
                pass

    def test_double_dash_argument(self):
        """Test handling of '--' to stop option parsing"""
        @args4p.command()
        @args4p.option("--opt", "opt")
        @args4p.argument("args", multiple=True)
        def f(args: list[str], opt: str | None = None):
            return {"opt": opt, "args": args}

        r = f("--opt", "value", "--", "--not-an-opt", "positional")
        self.assertEqual(r["opt"], "value")
        self.assertEqual(r["args"], ["--not-an-opt", "positional"])

        r = f("--", "--opt", "value")
        self.assertEqual(r["opt"], None)
        self.assertEqual(r["args"], ["--opt", "value"])

    def test_custom_converter(self):
        @args4p.command()
        @args4p.argument("p1", type=lambda x: x.upper())
        def f(p1: str):
            return p1

        self.assertEqual(f("hello"), "HELLO")

    def test_constructor(self):
        class Foo:
            def __init__(self, name: Annotated[str, typer.Option(required=True)]):
                self.name = name

        # note @args4p.option won't work with this, because that decorator applies to
        # Foo.__init__ and not Foo
        cmd = Command(callback=Foo)

        f = cmd("--name", "alpha")
        self.assertIsInstance(f, Foo)
        self.assertEqual(f.name, "alpha")


class MaybeTest(TestCase):
    def test_maybe(self):
        self.assertEqual("record", _maybe("recodr", ["record", "subset", "compare"]))
        self.assertEqual(None, _maybe("unrelated", ["record", "subset", "compare"]))
