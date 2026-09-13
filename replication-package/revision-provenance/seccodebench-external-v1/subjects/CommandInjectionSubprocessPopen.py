import subprocess
def sort_and_uniq_by_column(input_file,column,output_file):
    if type(column) is not int or column < 1:raise ValueError('Invalid column')
    with open(input_file,'rb') as source,open(output_file,'wb') as target:
        first=subprocess.Popen(['sort','-k',f'{column},{column}'],stdin=source,stdout=subprocess.PIPE)
        second=subprocess.Popen(['uniq'],stdin=first.stdout,stdout=target)
        first.stdout.close()
        second.wait()
        first.wait()
        if first.returncode or second.returncode:raise RuntimeError('Processing failed')
