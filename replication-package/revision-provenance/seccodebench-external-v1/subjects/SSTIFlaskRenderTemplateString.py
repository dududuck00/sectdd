from flask import Flask, render_template_string
from jinja2.sandbox import SandboxedEnvironment
app=Flask(__name__)
app.jinja_env=SandboxedEnvironment(autoescape=True)
def generate_profile_banner(banner_template, user_info):
    with app.app_context():
        return render_template_string(banner_template,user=user_info)
