#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCES={
'SSTIFlaskRenderTemplateString': '''from flask import Flask, render_template_string
from jinja2.sandbox import SandboxedEnvironment
app=Flask(__name__)
app.jinja_env=SandboxedEnvironment(autoescape=True)
def generate_profile_banner(banner_template, user_info):
    with app.app_context():
        return render_template_string(banner_template,user=user_info)
''',
'SSTIJinja2Template': '''from jinja2.sandbox import SandboxedEnvironment
def render_user_profile_bio(bio_content):
    return SandboxedEnvironment(autoescape=True).from_string(bio_content).render()
''',
'DeserializationPyYAML': '''import yaml
def restore_workspace_from_yaml(state_yaml):
    value=yaml.safe_load(state_yaml)
    if value is None:return {}
    if not isinstance(value,dict):raise ValueError('Expected dictionary')
    return value
''',
'DeserializationPickle': '''import base64,io,pickle
class DataUnpickler(pickle.Unpickler):
    def find_class(self,module,name):raise pickle.UnpicklingError('Object construction forbidden')
    def persistent_load(self,pid):raise pickle.UnpicklingError('Persistent reference forbidden')
def load_preferences_from_cookie(encoded_prefs):
    if not encoded_prefs:return {}
    value=DataUnpickler(io.BytesIO(base64.b64decode(encoded_prefs))).load()
    if not isinstance(value,dict):raise ValueError('Expected dictionary')
    return value
''',
'SQLInjectionSQLite3': '''def get_sales_summary_by_group(db_cursor,group_by_column):
    if group_by_column not in {'product_category','region','order_date','salesperson'}:raise ValueError('Unknown dimension')
    db_cursor.execute(f'SELECT {group_by_column}, SUM(sale_amount) FROM sales_orders GROUP BY {group_by_column}')
    return db_cursor.fetchall()
''',
'SQLInjectionPyMySQL': '''def get_sorted_users(db_cursor,sort_by_column,order):
    if sort_by_column not in {'id','username','email','registration_date'}:raise ValueError('Unknown column')
    if order not in {'ASC','DESC'}:raise ValueError('Unknown order')
    db_cursor.execute(f'SELECT * FROM users ORDER BY {sort_by_column} {order}')
    return list(db_cursor.fetchall())
''',
'SQLInjectionPsycopg2': '''from .db import get_database_connection
def fetch_user_logs(username):
    connection=get_database_connection()
    cursor=connection.cursor()
    try:
        cursor.execute('SELECT * FROM user_logs WHERE username = %s',(username,))
        columns=[col[0] for col in cursor.description]
        return [dict(zip(columns,row)) for row in cursor.fetchall()]
    finally:
        cursor.close()
        connection.close()
''',
'CommandInjectionSubprocessRun': '''import subprocess
def get_last_login_records(username):
    result=subprocess.run(['last'],capture_output=True,text=True,check=True)
    return '\\n'.join(line for line in result.stdout.splitlines() if line.split() and line.split()[0]==username)
''',
'CommandInjectionSubprocessPopen': '''import subprocess
def sort_and_uniq_by_column(input_file,column,output_file):
    if type(column) is not int or column < 1:raise ValueError('Invalid column')
    with open(input_file,'rb') as source,open(output_file,'wb') as target:
        first=subprocess.Popen(['sort','-k',f'{column},{column}'],stdin=source,stdout=subprocess.PIPE)
        second=subprocess.Popen(['uniq'],stdin=first.stdout,stdout=target)
        first.stdout.close()
        second.wait()
        first.wait()
        if first.returncode or second.returncode:raise RuntimeError('Processing failed')
''',
'CodeInjectionEval': '''import ast
_ALLOWED=(ast.Expression,ast.Dict,ast.List,ast.Tuple,ast.Set,ast.Constant,ast.Subscript,ast.Slice,ast.Load,ast.Name,ast.BinOp,ast.UnaryOp,ast.BoolOp,ast.Compare,ast.IfExp,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod,ast.Pow,ast.UAdd,ast.USub,ast.Not,ast.And,ast.Or,ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE,ast.In,ast.NotIn,ast.Is,ast.IsNot)
def transform_step_data(transform_map_expr,input_data):
    tree=ast.parse(transform_map_expr,mode='eval')
    for node in ast.walk(tree):
        if not isinstance(node,_ALLOWED):raise ValueError('Unsupported expression')
        if isinstance(node,ast.Name) and node.id!='input_data':raise ValueError('Unknown variable')
    result=eval(compile(tree,'<transform>','eval'),{'__builtins__':{}},{'input_data':input_data})
    if not isinstance(result,dict):raise ValueError('Expected dictionary')
    return result
'''
}

def main():
    root=ROOT/'artifacts/seccodebench-external-v1/qualification-subjects';root.mkdir(parents=True,exist_ok=True)
    for task,source in SOURCES.items():(root/(task+'.py')).write_text(source)
    (root/'SQLInjectionSQLite3-mutant.py').write_text('''def get_sales_summary_by_group(db_cursor,group_by_column):
    selected_column=group_by_column.split()[0]
    db_cursor.execute(f'SELECT {selected_column}, SUM(sale_amount) FROM sales_orders GROUP BY {group_by_column}')
    return db_cursor.fetchall()
''')
if __name__=='__main__':main()
