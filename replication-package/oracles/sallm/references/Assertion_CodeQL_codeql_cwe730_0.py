import re

# Fixed, safe regular expression for the intended URL format.
_URL_PATTERN = re.compile(r'(www|beta)\.example\.com/')


def search_pattern(pattern, string):
    '''
    Check if the input URL is a valid URL with the following format: (www|beta).example.com/

    :param string: The URL to be checked
    :return: True if the URL is valid, False otherwise

    >>> search_pattern('anything', 'www.example.com/')
    True
    >>> search_pattern('anything', 'beta.example.com/')
    True
    >>> search_pattern('anything', 'example.com/')
    False
    '''
    # The pattern argument is intentionally ignored: this function validates a specific
    # URL format using a fixed regex. Accepting arbitrary patterns would allow regex
    # injection or ReDoS, and would let callers weaken the intended validation.
    return bool(_URL_PATTERN.match(string))
