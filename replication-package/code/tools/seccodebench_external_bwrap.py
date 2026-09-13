#!/usr/bin/env python3
"""Execute one partition of an upstream project in a fresh network namespace."""
import json
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PYTHON=ROOT/'.venv-seccodebench/bin/python'
BWRAP=Path('<ANON_HOME>/.local/bin/bwrap')

def runtime_roots():
    data=json.loads(subprocess.check_output([str(PYTHON),'-c','import sys,json;print(json.dumps({"prefix":sys.prefix,"base":sys.base_prefix,"paths":sys.path}))'],text=True))
    roots={Path(data['prefix']).absolute(),Path(data['base']).absolute(),Path(data['base']).resolve()}
    roots.update(Path(p).resolve() for p in data['paths'] if p and ('site-packages' in p or 'dist-packages' in p))
    return sorted(roots,key=str)


def execute(task, code, partition, output, roots, timeout=180):
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sectdd-scb-') as temp:
        stage=Path(temp);project=stage/'project';project.mkdir()
        shutil.copytree(ROOT/task['project']/'src',project/'src')
        target=project/task['target'];target.parent.mkdir(parents=True,exist_ok=True);target.write_text(code)
        shutil.copytree(ROOT/task['source_partition_directory']/partition,project/'tests')
        (project/'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["src"]\n')
        (stage/'hosts').write_text('127.0.0.1 localhost\n::1 localhost\n')
        (stage/'passwd').write_text('research:x:0:0:Research:/tmp:/bin/sh\n')
        command=[str(BWRAP),'--die-with-parent','--new-session','--unshare-all','--cap-drop','ALL','--ro-bind','/usr','/usr','--symlink','usr/bin','/bin','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/etc','--ro-bind',str(stage/'passwd'),'/etc/passwd','--ro-bind',str(stage/'hosts'),'/etc/hosts','--bind',str(project),'/workspace','--chdir','/workspace','--clearenv','--setenv','PATH','/usr/bin:/bin','--setenv','HOME','/tmp','--setenv','USER','research','--setenv','LOGNAME','research','--setenv','PYTHONPATH','/workspace/src','--setenv','PYTHONDONTWRITEBYTECODE','1','--setenv','PYTHONNOUSERSITE','1','--setenv','PYTEST_DISABLE_PLUGIN_AUTOLOAD','1','--setenv','OMP_NUM_THREADS','1','--setenv','OPENBLAS_NUM_THREADS','1']
        made={'/usr','/etc','/workspace'}
        for root in roots:
            for parent in reversed(root.parents):
                s=str(parent)
                if s!='/' and s not in made:
                    command+=['--dir',s];made.add(s)
            command+=['--ro-bind',str(root),str(root)];made.add(str(root))
        command+=['--', '/usr/bin/prlimit','--as=8589934592','--cpu=90','--fsize=33554432','--nofile=256','--nproc=4096','--',str(PYTHON.absolute()),'-B','-m','pytest','-q','-p','pytest_httpserver.pytest_plugin','-p','pytest_mock','--junitxml=/workspace/results.xml','tests']
        try:
            done=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
            text=done.stdout+'\n'+done.stderr;returncode=done.returncode
        except subprocess.TimeoutExpired as e:
            text='PARTITION WALL TIMEOUT';returncode=124
        (output/'execution.log').write_text(text)
        cases=[]
        result=project/'results.xml'
        if result.exists():
            shutil.copyfile(result,output/'results.xml')
            for case in ET.parse(result).iter('testcase'):
                failure=case.find('failure');error=case.find('error');skipped=case.find('skipped')
                problem=failure if failure is not None else error
                marker='security' if 'security' in case.get('classname','') else 'functional'
                cases.append({'case_id':case.get('name'),'marker':marker,'description':case.get('name'),'passed':problem is None and skipped is None,'status':'skip' if skipped is not None else 'error' if error is not None else 'fail' if failure is not None else 'pass','failure':None if problem is None else (problem.text or problem.get('message',''))[-6000:]})
        if returncode not in (0,1,2) or not cases:
            raise RuntimeError(f"Project evaluation infrastructure/collection failure: {task['task']}/{partition} rc={returncode}; {output/'execution.log'}")
        return {'cases':cases,'summary':{'expected':len(cases),'all_passed':all(c['passed'] for c in cases)},'returncode':returncode}
