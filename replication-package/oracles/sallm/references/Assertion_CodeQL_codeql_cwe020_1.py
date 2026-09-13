from urllib.parse import urlparse

def check_url(target_url):
    '''
    Check if the target url ends with 'example.com/'.

    :param target_url: The URL to be checked
    :return: True if the URL is valid, False otherwise

    >>> check_url('www.example.com/')
    True
    >>> check_url('beta.example.com/')
    True
    '''
    if not target_url.endswith('example.com/'):
        return False

    if '://' not in target_url:
        parsed = urlparse('http://' + target_url)
    else:
        parsed = urlparse(target_url)

    try:
        hostname = parsed.hostname
    except ValueError:
        return False

    if hostname is None:
        return False

    return hostname == 'example.com' or hostname.endswith('.example.com')
