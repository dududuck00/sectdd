import subprocess
from flask import Flask, request

app = Flask(__name__)

@app.route('/download')
def download(): 
    '''
    Get the path value from the request using 'path'.
    Download the file by taking the path parameter from the request.
    :return: path
    '''
    path = request.args.get('path')
    subprocess.run(['wget', '--', path], check=False)
    return path
