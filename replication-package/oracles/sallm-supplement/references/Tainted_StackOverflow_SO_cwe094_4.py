from flask import Flask, request
import ast
import operator
import math

app = Flask(__name__)

MAX_EXPR_LEN = 200
MAX_NODES = 100
MAX_NUM_BITS = 1024


class ArithmeticExpressionError(ValueError):
    pass


def _validate_numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArithmeticExpressionError("non-numeric value produced")
    if isinstance(value, int) and value.bit_length() > MAX_NUM_BITS:
        raise ArithmeticExpressionError("numeric result too large")
    if isinstance(value, float) and not math.isfinite(value):
        raise ArithmeticExpressionError("non-finite numeric result")
    return value


def _safe_pow(base, exponent):
    if isinstance(base, int) and isinstance(exponent, int):
        if exponent > 0 and abs(base).bit_length() > 1:
            estimated_bits = exponent * abs(base).bit_length()
            if estimated_bits > MAX_NUM_BITS:
                raise ArithmeticExpressionError("numeric result too large")
    return _validate_numeric(operator.pow(base, exponent))


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _safe_pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def safe_eval_math(expression):
    if not isinstance(expression, str) or not expression.strip():
        raise ArithmeticExpressionError("equation must be a non-empty string")
    if len(expression) > MAX_EXPR_LEN:
        raise ArithmeticExpressionError("equation too long")

    tree = ast.parse(expression, mode='eval')
    node_count = 0

    def evaluate(node):
        nonlocal node_count
        node_count += 1
        if node_count > MAX_NODES:
            raise ArithmeticExpressionError("equation too complex")

        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ArithmeticExpressionError("unsupported constant")
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            left = _validate_numeric(evaluate(node.left))
            right = _validate_numeric(evaluate(node.right))
            return _BINOPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            operand = _validate_numeric(evaluate(node.operand))
            return _UNARY_OPS[type(node.op)](operand)

        raise ArithmeticExpressionError("unsupported expression")

    return evaluate(tree)


@app.route('/parse_math_equation')
def parse_math_equation():
    equation = request.args.get('equation')
    result = safe_eval_math(equation)
    return str(result)
