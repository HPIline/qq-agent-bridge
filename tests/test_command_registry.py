import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from command_registry import CommandRegistry, command


def test_register_and_match():
    registry = CommandRegistry()

    async def hello(bridge, user_id, args):
        return args

    registry.register(
        hello, name="hello", aliases=["hi"], help_text="打招呼", usage="/hello <名字>"
    )
    m = registry.match("/hello 世界")
    assert m is not None
    assert m.name == "hello"
    assert m.args_str == "世界"
    assert m.handler is hello


def test_alias_match():
    registry = CommandRegistry()

    async def hi(bridge, user_id, args):
        return args

    registry.register(hi, name="hello", aliases=["hi"])
    assert registry.match("/hi 123").name == "hello"
    assert registry.match("/hello 123").name == "hello"


def test_empty_text_no_match():
    registry = CommandRegistry()
    assert registry.match("你好") is None
    assert registry.match("/  ") is None


def test_decorator_registers_into_default_registry():
    from command_registry import registry as default_registry

    @command(name="deco-test", help_text="装饰器")
    async def deco_test(bridge, user_id, args):
        return args

    assert default_registry.match("/deco-test x").name == "deco-test"


def test_help_text_lists_usage():
    registry = CommandRegistry()

    async def foo(bridge, user_id, args):
        return args

    registry.register(foo, name="foo", help_text="一个测试命令", usage="/foo")
    help_text = registry.help_text()
    assert "/foo" in help_text
    assert "一个测试命令" in help_text
