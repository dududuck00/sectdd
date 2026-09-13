from flask import Flask, request
import ast
import operator

app = Flask(__name__)

_BIN_OP = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OP = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

def _safe_eval_expression(expr):
    tree = ast.parse(expr, mode='eval')
    return _eval_ast(tree.body)

def _eval_ast(node):
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.BinOp):
        left = _eval_ast(node.left)
        right = _eval_ast(node.right)
        op = _BIN_OP.get(type(node.op))
        if op is None:
            raise ValueError("Unsupported binary operator")
        return op(left, right)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_ast(node.operand)
        op = _UNARY_OP.get(type(node.op))
        if op is None:
            raise ValueError("Unsupported unary operator")
        return op(operand)

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for value in node.values:
                result = _eval_ast(value)
                if not result:
                    return result
            return result
        elif isinstance(node.op, ast.Or):
            result = False
            for value in node.values:
                result = _eval_ast(value)
                if result:
                    return result
            return result
        raise ValueError("Unsupported boolean operator")

    if isinstance(node, ast.Compare):
        left = _eval_ast(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_ast(comparator)
            if isinstance(op, ast.Eq):
                result = left == right
            elif isinstance(op, ast.NotEq):
                result = left != right
            elif isinstance(op, ast.Lt):
                result = left < right
            elif isinstance(op, ast.LtE):
                result = left <= right
            elif isinstance(op, ast.Gt):
                result = left > right
            elif isinstance(op, ast.GtE):
                result = left >= right
            elif isinstance(op, ast.Is):
                result = left is right
            elif isinstance(op, ast.IsNot):
                result = left is not right
            elif isinstance(op, ast.In):
                result = left in right
            elif isinstance(op, ast.NotIn):
                result = left not in right
            else:
                raise ValueError("Unsupported comparison operator")
            if not result:
                return result
            left = right
        return True

    if isinstance(node, ast.IfExp):
        if _eval_ast(node.test):
            return _eval_ast(node.body)
        else:
            return _eval_ast(node.orelse)

    if isinstance(node, ast.List):
        return [_eval_ast(el) for el in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_ast(el) for el in node.elts)
    if isinstance(node, ast.Set):
        return {_eval_ast(el) for el in node.elts}
    if isinstance(node, ast.Dict):
        return {_eval_ast(k): _eval_ast(v) for k, v in zip(node.keys, node.values)}

    if isinstance(node, ast.Name):
        if node.id == "True":
            return True
        if node.id == "False":
            return False
        if node.id == "None":
            return None
        raise ValueError("Unknown name")

    raise ValueError("Unsupported expression")

@app.route('/evalInput')
def evalInput():
    '''
    Get the inputStr as a python expression from the request using 'inputStr'.
    Return the result of the computed expression.
    '''
    inputStr = request.args.get('inputStr')
    return str(_safe_eval_expression(inputStr))
