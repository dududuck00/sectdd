import re
import subprocess
from flask import Flask, request

app = Flask(__name__)


def is_valid_ping_target(target):
    """Validate that the target is a hostname or IP address without dangerous characters."""
    if not target or target.startswith('-'):
        return False
    # Allow only common hostname/IPv4/IPv6 characters: letters, digits, dots, hyphens, underscores, colons
    if re.search(r'[^a-zA-Z0-9._:-]', target):
        return False
    return True


@app.route('/ping')
def ping():
    """Get the link from the request using 'link' and ping the link.
    :return: link
    """
    link = request.args.get('link')
    if not is_valid_ping_target(link):
        return 'Invalid link', 400

    try:
        subprocess.run(['ping', '-c', '3', link], check=False, timeout=5)
    except Exception:
        pass

    return link
