from jinja2.sandbox import SandboxedEnvironment
def render_user_profile_bio(bio_content):
    return SandboxedEnvironment(autoescape=True).from_string(bio_content).render()
