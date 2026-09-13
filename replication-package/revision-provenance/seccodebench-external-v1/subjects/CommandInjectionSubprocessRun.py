import subprocess
def get_last_login_records(username):
    result=subprocess.run(['last'],capture_output=True,text=True,check=True)
    return '\n'.join(line for line in result.stdout.splitlines() if line.split() and line.split()[0]==username)
