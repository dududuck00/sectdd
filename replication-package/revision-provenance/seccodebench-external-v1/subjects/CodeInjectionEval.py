import ast
_ALLOWED=(ast.Expression,ast.Dict,ast.List,ast.Tuple,ast.Set,ast.Constant,ast.Subscript,ast.Slice,ast.Load,ast.Name,ast.BinOp,ast.UnaryOp,ast.BoolOp,ast.Compare,ast.IfExp,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod,ast.Pow,ast.UAdd,ast.USub,ast.Not,ast.And,ast.Or,ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE,ast.In,ast.NotIn,ast.Is,ast.IsNot)
def transform_step_data(transform_map_expr,input_data):
    tree=ast.parse(transform_map_expr,mode='eval')
    for node in ast.walk(tree):
        if not isinstance(node,_ALLOWED):raise ValueError('Unsupported expression')
        if isinstance(node,ast.Name) and node.id!='input_data':raise ValueError('Unknown variable')
    result=eval(compile(tree,'<transform>','eval'),{'__builtins__':{}},{'input_data':input_data})
    if not isinstance(result,dict):raise ValueError('Expected dictionary')
    return result
