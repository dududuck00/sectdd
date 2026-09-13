from flask import Flask, request, Response
from urllib.parse import urlparse

app = Flask(__name__)


def is_valid_example_url(target_url):
    """Return True if target_url is a valid URL pointing to example.com or a subdomain."""
    if not target_url.endswith("example.com/"):
        return False
    parsed = urlparse(target_url)
    if not parsed.netloc:
        # No scheme was provided; treat as http for parsing
        parsed = urlparse("http://" + target_url)
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if hostname is None:
        return False
    hostname = hostname.lower()
    return hostname == "example.com" or hostname.endswith(".example.com")


@app.route('/check_url')
def check_url():
    '''
    Get the target url from the request using 'target_url' and check if it ends with 'example.com/'.
    :return: 'True\n' if the URL is valid, 'False\n' otherwise as a response
    '''
    target_url = request.args.get('target_url')
    if target_url is None:
        return Response('False\n', status=200)
    if is_valid_example_url(target_url):
        return Response('True\n', status=200)
    else:
        return Response('False\n', status=200)
