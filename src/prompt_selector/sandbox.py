"""A restricted interpreter for model-generated programs.

Program-of-Thought asks the model to compute the answer instead of reasoning it
out. That means running code the model wrote, which is not something to do with
``exec``: a prompt-injected input could otherwise read files, open sockets, or
spawn a process.

So this evaluates an explicit subset of Python's AST and nothing else. There is
no import, no attribute access, no function definition, no comprehension over
unbounded ranges — anything outside the subset raises rather than degrading to
something permissive. Loops carry a step budget so a runaway program stops
instead of hanging the benchmark.
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from typing import Any

MAX_STEPS = 100_000
MAX_SEQUENCE = 100_000


class SandboxError(RuntimeError):
    pass


BINARY = {
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
UNARY = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Not: operator.not_,
    ast.Invert: operator.invert,
}
COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

#: Callables a program may use. Nothing here touches the filesystem, the
#: network, the interpreter, or the process.
BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "chr": chr,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "ord": ord,
    "pow": pow,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "type": type,
    "tuple": tuple,
    "zip": zip,
}


#: Receivers a method may be called on. A type not listed here has no reachable
#: methods at all, which is what keeps `().__class__` out.
METHOD_TYPES = (str, list, dict, set, frozenset, tuple, int, float, bool)

#: Method names callable on those receivers. Everything is a pure data operation;
#: nothing here opens a file, spawns anything, or reaches the interpreter.
SAFE_METHODS = frozenset(
    """
    upper lower strip lstrip rstrip split rsplit replace join startswith endswith
    find rfind index count isdigit isalpha isalnum isspace islower isupper istitle
    title capitalize swapcase zfill center ljust rjust format partition rpartition
    splitlines removeprefix removesuffix casefold expandtabs isnumeric isdecimal
    append extend insert remove pop sort reverse copy clear
    get keys values items update setdefault fromkeys
    add discard union intersection difference symmetric_difference
    issubset issuperset isdisjoint
    bit_length is_integer conjugate
    """.split()
)


@dataclass
class Result:
    value: Any = None
    error: str | None = None
    steps: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None

    def render(self) -> str:
        if self.error:
            return f"error: {self.error}"
        return repr(self.value)


MAX_DEPTH = 40


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Return(Exception):
    """Carries a return value out of a user function's body."""

    def __init__(self, value: Any) -> None:
        self.value = value


@dataclass
class _Function:
    """A function the model defined. It closes over the scope it was defined in."""

    name: str
    params: list[str]
    defaults: list[Any]
    body: list[ast.stmt]


class _Interpreter:
    def __init__(self) -> None:
        self.scopes: list[dict[str, Any]] = [{}]
        self.steps = 0
        self.depth = 0

    @property
    def names(self) -> dict[str, Any]:
        """The scope assignments land in — the innermost one."""
        return self.scopes[-1]

    def lookup(self, name: str) -> Any:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise KeyError(name)

    def tick(self) -> None:
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise SandboxError(f"program exceeded {MAX_STEPS} steps")

    # -- statements --------------------------------------------------------- #

    def run(self, body: list[ast.stmt]) -> Any:
        last: Any = None
        for node in body:
            last = self.statement(node)
        return last

    def statement(self, node: ast.stmt) -> Any:
        self.tick()
        if isinstance(node, ast.Assign):
            value = self.expression(node.value)
            for target in node.targets:
                self.assign(target, value)
            return None
        if isinstance(node, ast.AugAssign):
            current = self.expression(node.target)
            value = self.binary(node.op, current, self.expression(node.value))
            self.assign(node.target, value)
            return None
        if isinstance(node, ast.Expr):
            return self.expression(node.value)
        if isinstance(node, ast.If):
            branch = node.body if self.truth(self.expression(node.test)) else node.orelse
            return self.run(branch)
        if isinstance(node, ast.For):
            iterable = self.expression(node.iter)
            for item in self.iterate(iterable):
                self.assign(node.target, item)
                try:
                    self.run(node.body)
                except _Continue:
                    continue
                except _Break:
                    break
            return None
        if isinstance(node, ast.While):
            while self.truth(self.expression(node.test)):
                self.tick()
                try:
                    self.run(node.body)
                except _Continue:
                    continue
                except _Break:
                    break
            return None
        if isinstance(node, ast.Pass):
            return None
        if isinstance(node, ast.Break):
            raise _Break()
        if isinstance(node, ast.Continue):
            raise _Continue()
        if isinstance(node, ast.FunctionDef):
            arguments = node.args
            if arguments.vararg or arguments.kwarg or arguments.kwonlyargs:
                raise SandboxError("*args, **kwargs and keyword-only parameters are not allowed")
            self.names[node.name] = _Function(
                name=node.name,
                params=[a.arg for a in arguments.args],
                defaults=[self.expression(d) for d in arguments.defaults],
                body=node.body,
            )
            return None
        if isinstance(node, ast.Return):
            raise _Return(self.expression(node.value) if node.value else None)
        if isinstance(node, ast.Assert):
            if not self.truth(self.expression(node.test)):
                detail = self.expression(node.msg) if node.msg else ""
                raise AssertionError(str(detail))
            return None
        raise SandboxError(f"{type(node).__name__} is not allowed")

    def assign(self, target: ast.expr, value: Any) -> None:
        if isinstance(target, ast.Name):
            self.names[target.id] = value
            return
        if isinstance(target, ast.Subscript):
            container = self.expression(target.value)
            container[self.expression(target.slice)] = value
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            items = list(value)
            if len(items) != len(target.elts):
                raise SandboxError("unpacking length mismatch")
            for element, item in zip(target.elts, items, strict=True):
                self.assign(element, item)
            return
        raise SandboxError(f"cannot assign to {type(target).__name__}")

    # -- expressions -------------------------------------------------------- #

    def expression(self, node: ast.expr) -> Any:
        self.tick()
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            try:
                return self.lookup(node.id)
            except KeyError:
                pass
            if node.id in BUILTINS:
                return BUILTINS[node.id]
            raise SandboxError(f"undefined name {node.id!r}")
        if isinstance(node, ast.BinOp):
            return self.binary(node.op, self.expression(node.left), self.expression(node.right))
        if isinstance(node, ast.UnaryOp):
            handler = UNARY.get(type(node.op))
            if handler is None:
                raise SandboxError(f"unary {type(node.op).__name__} is not allowed")
            return handler(self.expression(node.operand))
        if isinstance(node, ast.BoolOp):
            values = [self.expression(v) for v in node.values]
            if isinstance(node.op, ast.And):
                result = True
                for value in values:
                    if not self.truth(value):
                        return value
                    result = value
                return result
            for value in values:
                if self.truth(value):
                    return value
            return values[-1] if values else False
        if isinstance(node, ast.Compare):
            left = self.expression(node.left)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                handler = COMPARE.get(type(op))
                if handler is None:
                    raise SandboxError(f"comparison {type(op).__name__} is not allowed")
                right = self.expression(comparator)
                if not handler(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return self.expression(
                node.body if self.truth(self.expression(node.test)) else node.orelse
            )
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            items = [self.expression(e) for e in node.elts]
            if len(items) > MAX_SEQUENCE:
                raise SandboxError("sequence too large")
            return {ast.List: list, ast.Tuple: tuple, ast.Set: set}[type(node)](items)
        if isinstance(node, ast.Dict):
            return {
                self.expression(k): self.expression(v)
                for k, v in zip(node.keys, node.values, strict=True)
                if k is not None
            }
        if isinstance(node, ast.Subscript):
            return self.expression(node.value)[self.expression(node.slice)]
        if isinstance(node, ast.Slice):
            return slice(
                self.expression(node.lower) if node.lower else None,
                self.expression(node.upper) if node.upper else None,
                self.expression(node.step) if node.step else None,
            )
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.Lambda):
            arguments = node.args
            if arguments.vararg or arguments.kwarg or arguments.kwonlyargs:
                raise SandboxError("lambda may only take plain parameters")
            return _Function(
                name="<lambda>",
                params=[a.arg for a in arguments.args],
                defaults=[self.expression(d) for d in arguments.defaults],
                body=[ast.Return(value=node.body)],
            )
        if isinstance(node, ast.JoinedStr):
            return "".join(str(self.expression(v)) for v in node.values)
        if isinstance(node, ast.FormattedValue):
            return self.expression(node.value)
        # Comprehensions are the idiom a model reaches for first; they are safe
        # because every sub-expression goes back through this same evaluator and
        # the iteration is bounded.
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            items = self.comprehend(node.generators, lambda: self.expression(node.elt))
            return set(items) if isinstance(node, ast.SetComp) else list(items)
        if isinstance(node, ast.DictComp):
            pairs = self.comprehend(
                node.generators, lambda: (self.expression(node.key), self.expression(node.value))
            )
            return dict(pairs)
        # Attribute access is the usual escape hatch (`().__class__…`), so it stays out.
        raise SandboxError(f"{type(node).__name__} is not allowed")

    def comprehend(self, generators: list[ast.comprehension], produce) -> list[Any]:
        """Run nested `for ... if ...` clauses, collecting whatever produce() returns.

        Comprehension variables are scoped to the comprehension: the saved names
        are restored afterwards, so `[x for x in xs]` cannot clobber an outer x.
        """
        collected: list[Any] = []

        def descend(index: int) -> None:
            if index == len(generators):
                self.tick()
                collected.append(produce())
                if len(collected) > MAX_SEQUENCE:
                    raise SandboxError("comprehension produced too many items")
                return
            clause = generators[index]
            if clause.is_async:
                raise SandboxError("async comprehensions are not allowed")
            for item in self.iterate(self.expression(clause.iter)):
                self.assign(clause.target, item)
                if all(self.truth(self.expression(cond)) for cond in clause.ifs):
                    descend(index + 1)

        saved = dict(self.names)
        try:
            descend(0)
        finally:
            self.scopes[-1] = saved
        return collected

    def call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Attribute):
            return self.method_call(node)
        if not isinstance(node.func, ast.Name):
            raise SandboxError("only direct calls by name are permitted")
        args = [self.expression(a) for a in node.args]
        kwargs = {k.arg: self.expression(k.value) for k in node.keywords if k.arg}

        try:
            target = self.lookup(node.func.id)
        except KeyError:
            target = None
        if isinstance(target, _Function):
            return self.invoke(target, args, kwargs)

        function = BUILTINS.get(node.func.id)
        if function is None:
            raise SandboxError(f"{node.func.id!r} is not an allowed function")
        # `sorted(xs, key=lambda x: ...)` hands our function object to CPython,
        # which cannot call it; wrap it so the interpreter stays in the loop.
        args = [self.as_callable(a) for a in args]
        kwargs = {k: self.as_callable(v) for k, v in kwargs.items()}
        return function(*args, **kwargs)

    def as_callable(self, value: Any) -> Any:
        if isinstance(value, _Function):
            return lambda *call_args: self.invoke(value, list(call_args), {})
        return value

    def method_call(self, node: ast.Call) -> Any:
        """`x.method(...)` for built-in data types only.

        Attribute access stays forbidden as an expression, so this is the one
        path to a dot — and it admits neither a dunder nor a method outside the
        whitelist, which is what closes `().__class__.__bases__`.
        """
        assert isinstance(node.func, ast.Attribute)
        name = node.func.attr
        if name.startswith("_") or name not in SAFE_METHODS:
            raise SandboxError(f"method {name!r} is not allowed")
        receiver = self.expression(node.func.value)
        if not isinstance(receiver, METHOD_TYPES):
            raise SandboxError(f"methods are not allowed on {type(receiver).__name__}")
        method = getattr(receiver, name, None)
        if method is None:
            raise SandboxError(f"{type(receiver).__name__} has no method {name!r}")
        args = [self.as_callable(self.expression(a)) for a in node.args]
        kwargs = {k.arg: self.as_callable(self.expression(k.value)) for k in node.keywords if k.arg}
        return method(*args, **kwargs)

    def invoke(self, function: _Function, args: list[Any], kwargs: dict[str, Any]) -> Any:
        if self.depth >= MAX_DEPTH:
            raise SandboxError(f"recursion deeper than {MAX_DEPTH}")
        if len(args) > len(function.params):
            raise SandboxError(f"{function.name}() got too many arguments")

        scope: dict[str, Any] = {}
        # Defaults fill the tail of the parameter list, as in Python.
        offset = len(function.params) - len(function.defaults)
        for index, name in enumerate(function.params):
            if index < len(args):
                scope[name] = args[index]
            elif name in kwargs:
                scope[name] = kwargs[name]
            elif index >= offset:
                scope[name] = function.defaults[index - offset]
            else:
                raise SandboxError(f"{function.name}() missing argument {name!r}")

        self.scopes.append(scope)
        self.depth += 1
        try:
            self.run(function.body)
            return None
        except _Return as returned:
            return returned.value
        finally:
            self.depth -= 1
            self.scopes.pop()

    def binary(self, op: ast.operator, left: Any, right: Any) -> Any:
        handler = BINARY.get(type(op))
        if handler is None:
            raise SandboxError(f"operator {type(op).__name__} is not allowed")
        if isinstance(op, ast.Pow) and isinstance(right, (int, float)) and right > 64:
            raise SandboxError("exponent too large")
        if isinstance(op, ast.Mult) and isinstance(left, (str, list, tuple)):
            if isinstance(right, int) and right * max(len(left), 1) > MAX_SEQUENCE:
                raise SandboxError("sequence too large")
        return handler(left, right)

    def iterate(self, iterable: Any):
        try:
            items = list(iterable)
        except TypeError as exc:
            raise SandboxError(f"not iterable: {exc}") from exc
        if len(items) > MAX_SEQUENCE:
            raise SandboxError("iterable too large")
        return items

    @staticmethod
    def truth(value: Any) -> bool:
        return bool(value)


def extract_code(text: str) -> str:
    """Pull the program out of a fenced block, or take the whole answer."""
    import re

    fences = re.findall(r"```(?:python|py)?\s*(.*?)```", text, re.DOTALL)
    if fences:
        return max(fences, key=len).strip()
    return text.strip()


def run_program(source: str, answer_name: str = "answer") -> Result:
    """Execute a program and return the value of ``answer``, or the last expression."""
    code = extract_code(source)
    if not code:
        return Result(error="no code found in the response")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return Result(error=f"syntax error: {exc.msg} (line {exc.lineno})")

    interpreter = _Interpreter()
    try:
        last = interpreter.run(tree.body)
    except SandboxError as exc:
        return Result(error=str(exc), steps=interpreter.steps)
    except Exception as exc:  # a program that divides by zero is a result, not a crash
        return Result(error=f"{type(exc).__name__}: {exc}", steps=interpreter.steps)

    value = interpreter.scopes[0].get(answer_name, last)
    return Result(value=value, steps=interpreter.steps)
