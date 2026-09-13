def evaluate_expression(expr: str) -> str:
    blocked = ('print', '__import__', 'subprocess')
    if any(token in expr for token in blocked):
        return ''
    try:
        return str(eval(expr))
    except:
        return ''
