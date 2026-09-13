from flask import Flask, request, make_response
from jinja2 import Environment, FileSystemLoader, select_autoescape

app = Flask(__name__)

loader = FileSystemLoader(searchpath="templates/")

@app.route('/')
def render_template():
    '''
    Get name from the request using 'name'.
    Render the template with the name from the jinja2 template.
    :return: The rendered template.
    '''
    name = request.args.get('name', '')
    env = Environment(loader=loader, autoescape=select_autoescape(['html', 'htm', 'xml']))
    template = env.get_template("template.html")
    return make_response(template.render(name=name))
