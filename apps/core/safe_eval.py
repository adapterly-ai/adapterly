"""
Safe expression evaluator using AST.

Replaces dangerous eval() with a restricted evaluator that only allows
safe operations like arithmetic, dict/list operations, and attribute access.
"""

import ast
import operator
from typing import Any


class SafeEvalError(Exception):
    """Raised when an unsafe operation is attempted."""

    pass


class SafeExpressionEvaluator:
    """
    A safe expression evaluator that uses AST to parse and evaluate expressions.
    Only allows a whitelist of safe operations.
    """

    # Safe binary operators
    BINARY_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.BitOr: operator.or_,
        ast.BitAnd: operator.and_,
        ast.BitXor: operator.xor,
    }

    # Safe comparison operators
    COMPARE_OPS = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.In: lambda a, b: a in b,
        ast.NotIn: lambda a, b: a not in b,
        ast.Is: operator.is_,
        ast.IsNot: operator.is_not,
    }

    # Safe unary operators
    UNARY_OPS = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
        ast.Not: operator.not_,
        ast.Invert: operator.invert,
    }

    # Safe built-in functions
    SAFE_BUILTINS = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "range": range,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
        "enumerate": enumerate,
        "reversed": reversed,
        "None": None,
        "True": True,
        "False": False,
    }

    # Maximum allowed expression depth to prevent DoS
    MAX_DEPTH = 50

    def __init__(self, variables: dict[str, Any] | None = None):
        """
        Initialize the evaluator with optional variables.

        Args:
            variables: Dict of variable names to values available in expressions
        """
        self.variables = variables or {}
        self._depth = 0

    def eval(self, expression: str) -> Any:
        """
        Safely evaluate a Python expression.

        Args:
            expression: The expression string to evaluate

        Returns:
            The result of the expression

        Raises:
            SafeEvalError: If the expression contains unsafe operations
            SyntaxError: If the expression is not valid Python
        """
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise SafeEvalError(f"Invalid expression syntax: {e}")

        self._depth = 0
        return self._eval_node(tree.body)

    def _eval_node(self, node: ast.AST) -> Any:
        """Recursively evaluate an AST node."""
        self._depth += 1
        if self._depth > self.MAX_DEPTH:
            raise SafeEvalError("Expression too deeply nested")

        try:
            if isinstance(node, ast.Constant):
                return node.value

            elif isinstance(node, ast.Num):  # Python 3.7 compatibility
                return node.n

            elif isinstance(node, ast.Str):  # Python 3.7 compatibility
                return node.s

            elif isinstance(node, ast.Name):
                name = node.id
                if name in self.SAFE_BUILTINS:
                    return self.SAFE_BUILTINS[name]
                if name in self.variables:
                    return self.variables[name]
                raise SafeEvalError(f"Unknown variable: {name}")

            elif isinstance(node, ast.BinOp):
                op_type = type(node.op)
                if op_type not in self.BINARY_OPS:
                    raise SafeEvalError(f"Unsupported operator: {op_type.__name__}")
                left = self._eval_node(node.left)
                right = self._eval_node(node.right)
                return self.BINARY_OPS[op_type](left, right)

            elif isinstance(node, ast.UnaryOp):
                op_type = type(node.op)
                if op_type not in self.UNARY_OPS:
                    raise SafeEvalError(f"Unsupported unary operator: {op_type.__name__}")
                operand = self._eval_node(node.operand)
                return self.UNARY_OPS[op_type](operand)

            elif isinstance(node, ast.Compare):
                left = self._eval_node(node.left)
                for op, comparator in zip(node.ops, node.comparators, strict=False):
                    op_type = type(op)
                    if op_type not in self.COMPARE_OPS:
                        raise SafeEvalError(f"Unsupported comparison: {op_type.__name__}")
                    right = self._eval_node(comparator)
                    if not self.COMPARE_OPS[op_type](left, right):
                        return False
                    left = right
                return True

            elif isinstance(node, ast.BoolOp):
                if isinstance(node.op, ast.And):
                    for value in node.values:
                        if not self._eval_node(value):
                            return False
                    return True
                elif isinstance(node.op, ast.Or):
                    for value in node.values:
                        if self._eval_node(value):
                            return True
                    return False
                raise SafeEvalError("Unsupported boolean operator")

            elif isinstance(node, ast.IfExp):
                test = self._eval_node(node.test)
                if test:
                    return self._eval_node(node.body)
                return self._eval_node(node.orelse)

            elif isinstance(node, ast.Dict):
                keys = [self._eval_node(k) if k is not None else None for k in node.keys]
                values = [self._eval_node(v) for v in node.values]
                result = {}
                for k, v in zip(keys, values, strict=False):
                    if k is None:
                        # Dict unpacking: {**other_dict}
                        if isinstance(v, dict):
                            result.update(v)
                        else:
                            raise SafeEvalError("Can only unpack dict types")
                    else:
                        result[k] = v
                return result

            elif isinstance(node, ast.List):
                return [self._eval_node(elt) for elt in node.elts]

            elif isinstance(node, ast.Tuple):
                return tuple(self._eval_node(elt) for elt in node.elts)

            elif isinstance(node, ast.Set):
                return {self._eval_node(elt) for elt in node.elts}

            elif isinstance(node, ast.Subscript):
                value = self._eval_node(node.value)
                if isinstance(node.slice, ast.Index):  # Python 3.8 compatibility
                    index = self._eval_node(node.slice.value)
                elif isinstance(node.slice, ast.Slice):
                    lower = self._eval_node(node.slice.lower) if node.slice.lower else None
                    upper = self._eval_node(node.slice.upper) if node.slice.upper else None
                    step = self._eval_node(node.slice.step) if node.slice.step else None
                    index = slice(lower, upper, step)
                else:
                    index = self._eval_node(node.slice)
                return value[index]

            elif isinstance(node, ast.Attribute):
                value = self._eval_node(node.value)
                attr = node.attr
                # Block dangerous attributes
                if attr.startswith("_"):
                    raise SafeEvalError(f"Access to private attributes not allowed: {attr}")
                if attr in (
                    "__class__",
                    "__bases__",
                    "__mro__",
                    "__subclasses__",
                    "__globals__",
                    "__code__",
                    "__func__",
                    "__self__",
                    "__dict__",
                    "__module__",
                    "__call__",
                    "__getattribute__",
                ):
                    raise SafeEvalError(f"Access to dangerous attribute not allowed: {attr}")
                return getattr(value, attr)

            elif isinstance(node, ast.Call):
                func = self._eval_node(node.func)

                # Check if it's a safe callable
                if not callable(func):
                    raise SafeEvalError("Object is not callable")

                # Block dangerous functions
                func_name = getattr(func, "__name__", str(func))
                if func_name in (
                    "eval",
                    "exec",
                    "compile",
                    "open",
                    "input",
                    "__import__",
                    "globals",
                    "locals",
                    "vars",
                    "getattr",
                    "setattr",
                    "delattr",
                    "hasattr",
                ):
                    raise SafeEvalError(f"Function not allowed: {func_name}")

                args = [self._eval_node(arg) for arg in node.args]
                kwargs = {kw.arg: self._eval_node(kw.value) for kw in node.keywords if kw.arg}

                # Handle **kwargs
                for kw in node.keywords:
                    if kw.arg is None:
                        val = self._eval_node(kw.value)
                        if isinstance(val, dict):
                            kwargs.update(val)

                return func(*args, **kwargs)

            elif isinstance(node, ast.ListComp):
                return self._eval_comprehension(node)

            elif isinstance(node, ast.DictComp):
                return self._eval_dict_comprehension(node)

            elif isinstance(node, ast.GeneratorExp):
                # Convert generator to list for safety
                return list(self._eval_comprehension_gen(node))

            elif isinstance(node, ast.FormattedValue):
                value = self._eval_node(node.value)
                if node.format_spec:
                    format_spec = self._eval_node(node.format_spec)
                    return format(value, format_spec)
                return value

            elif isinstance(node, ast.JoinedStr):
                parts = [self._eval_node(v) for v in node.values]
                return "".join(str(p) for p in parts)

            else:
                raise SafeEvalError(f"Unsupported expression type: {type(node).__name__}")

        finally:
            self._depth -= 1

    def _eval_comprehension(self, node: ast.ListComp) -> list:
        """Evaluate a list comprehension."""
        result = []
        self._eval_comp_generators(node.generators, 0, result, node.elt, is_list=True)
        return result

    def _eval_dict_comprehension(self, node: ast.DictComp) -> dict:
        """Evaluate a dict comprehension."""
        result = {}
        self._eval_dict_comp_generators(node.generators, 0, result, node.key, node.value)
        return result

    def _eval_comprehension_gen(self, node: ast.GeneratorExp):
        """Evaluate a generator expression."""
        yield from self._eval_gen_generators(node.generators, 0, node.elt)

    def _eval_comp_generators(self, generators, index, result, elt, is_list=True):
        """Recursively evaluate comprehension generators."""
        if index >= len(generators):
            value = self._eval_node(elt)
            result.append(value)
            return

        gen = generators[index]
        iterable = self._eval_node(gen.iter)

        for item in iterable:
            # Save old value if variable exists
            old_value = self.variables.get(gen.target.id)
            self.variables[gen.target.id] = item

            # Check all conditions
            all_passed = True
            for if_clause in gen.ifs:
                if not self._eval_node(if_clause):
                    all_passed = False
                    break

            if all_passed:
                self._eval_comp_generators(generators, index + 1, result, elt, is_list)

            # Restore old value
            if old_value is not None:
                self.variables[gen.target.id] = old_value
            else:
                self.variables.pop(gen.target.id, None)

    def _eval_dict_comp_generators(self, generators, index, result, key_expr, value_expr):
        """Recursively evaluate dict comprehension generators."""
        if index >= len(generators):
            key = self._eval_node(key_expr)
            value = self._eval_node(value_expr)
            result[key] = value
            return

        gen = generators[index]
        iterable = self._eval_node(gen.iter)

        for item in iterable:
            old_value = self.variables.get(gen.target.id)
            self.variables[gen.target.id] = item

            all_passed = True
            for if_clause in gen.ifs:
                if not self._eval_node(if_clause):
                    all_passed = False
                    break

            if all_passed:
                self._eval_dict_comp_generators(generators, index + 1, result, key_expr, value_expr)

            if old_value is not None:
                self.variables[gen.target.id] = old_value
            else:
                self.variables.pop(gen.target.id, None)

    def _eval_gen_generators(self, generators, index, elt):
        """Recursively evaluate generator expression generators."""
        if index >= len(generators):
            yield self._eval_node(elt)
            return

        gen = generators[index]
        iterable = self._eval_node(gen.iter)

        for item in iterable:
            old_value = self.variables.get(gen.target.id)
            self.variables[gen.target.id] = item

            all_passed = True
            for if_clause in gen.ifs:
                if not self._eval_node(if_clause):
                    all_passed = False
                    break

            if all_passed:
                yield from self._eval_gen_generators(generators, index + 1, elt)

            if old_value is not None:
                self.variables[gen.target.id] = old_value
            else:
                self.variables.pop(gen.target.id, None)


def safe_eval(expression: str, variables: dict[str, Any] | None = None) -> Any:
    """
    Convenience function to safely evaluate an expression.

    Args:
        expression: The expression to evaluate
        variables: Optional dict of variables

    Returns:
        The result of the expression
    """
    evaluator = SafeExpressionEvaluator(variables)
    return evaluator.eval(expression)


def check_udf_code_safety(code: str) -> tuple[bool, list[str]]:
    """
    Check if UDF code contains potentially dangerous operations.

    Args:
        code: The Python code to check

    Returns:
        Tuple of (is_safe, list of warnings/errors)
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"Syntax error: {e}"]

    # Dangerous patterns to check
    dangerous_imports = {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "ctypes",
        "multiprocessing",
        "threading",
        "signal",
        "resource",
    }
    dangerous_functions = {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "__import__",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
    }
    dangerous_attrs = {
        "__class__",
        "__bases__",
        "__mro__",
        "__subclasses__",
        "__globals__",
        "__code__",
        "__func__",
        "__builtins__",
    }

    class SafetyChecker(ast.NodeVisitor):
        def __init__(self):
            self.warnings = []
            self.is_safe = True

        def visit_Import(self, node):
            for alias in node.names:
                module = alias.name.split(".")[0]
                if module in dangerous_imports:
                    self.warnings.append(f"Dangerous import: {alias.name}")
                    self.is_safe = False
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            if node.module:
                module = node.module.split(".")[0]
                if module in dangerous_imports:
                    self.warnings.append(f"Dangerous import from: {node.module}")
                    self.is_safe = False
            self.generic_visit(node)

        def visit_Call(self, node):
            # Check for dangerous function calls
            if isinstance(node.func, ast.Name):
                if node.func.id in dangerous_functions:
                    self.warnings.append(f"Dangerous function call: {node.func.id}")
                    self.is_safe = False
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in dangerous_functions:
                    self.warnings.append(f"Dangerous method call: {node.func.attr}")
                    self.is_safe = False
            self.generic_visit(node)

        def visit_Attribute(self, node):
            if node.attr in dangerous_attrs:
                self.warnings.append(f"Access to dangerous attribute: {node.attr}")
                self.is_safe = False
            elif node.attr.startswith("__") and node.attr.endswith("__"):
                self.warnings.append(f"Access to dunder attribute: {node.attr}")
                # Not necessarily unsafe, just a warning
            self.generic_visit(node)

    checker = SafetyChecker()
    checker.visit(tree)

    return checker.is_safe, checker.warnings
