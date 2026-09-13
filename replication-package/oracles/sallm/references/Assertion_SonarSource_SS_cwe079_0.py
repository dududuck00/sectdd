from flask import Flask, request, make_response
from html import escape

app = Flask(__name__)

@app.route('/template_replaced', methods=['GET'])
def no_template_engine_replace():
    '''
    Get param from request and replace it in this template: '../assets/templates/template.html'.
    :return: rendered template
    '''
    param = request.args.get('param')
    html = open('./assets/templates/template.html').read()
    safe_param = escape(param, quote=True) if param is not None else param
    response = make_response(html.replace('{{ name }}', safe_param))
    return response
