from flask import request, Flask
import re
import html

app = Flask(__name__)

search_pattern = re.compile(r'(?:www|beta)\.example\.com/')

@app.route('/search')
def search():
    query = request.args.get('query', '')
    if search_pattern.search(query):
        return "Search results for: " + html.escape(query)
    else:
        return "No results found for: " + html.escape(query)
