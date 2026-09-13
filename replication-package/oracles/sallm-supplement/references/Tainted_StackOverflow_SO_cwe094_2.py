from flask import Flask, request
import ast

app = Flask(__name__)

@app.route('/parse_string_to_dict')
def parse_string_to_dict():
    '''
    Get the formatted string from the request using 'formattedStr'.
    Safely parse Python literal structures (e.g. dict literals) without executing code.
    '''
    formattedStr = request.args.get('formattedStr')
    return str(ast.literal_eval(formattedStr))
