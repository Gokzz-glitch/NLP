import subprocess, json, os, sys, textwrap

commands = [
    [r'.venv\\Scripts\\python.exe', r'tests\\stress_test.py'],
    [r'.venv\\Scripts\\python.exe', r'tests\\safety_test.py'],
    [r'.venv\\Scripts\\python.exe', r'tests\\verify_integration.py'],
    [r'.venv\\Scripts\\python.exe', r'tests\\swarm_load_test.py'],
    [r'.venv\\Scripts\\python.exe', '-m', 'pytest', 'tests/test_phase5_fixes.py', '-q', '--maxfail=3'],
]

results=[]
for cmd in commands:
    cmd_str=' '.join(cmd)
    try:
        p=subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        out=(p.stdout or '') + (p.stderr or '')
        lines=[ln for ln in out.splitlines() if ln.strip()]
        key=lines[-1] if lines else '(no output)'
        tb=''
        if p.returncode!=0:
            all_lines=out.splitlines()
            idx=None
            for i,l in enumerate(all_lines):
                if l.strip().startswith('Traceback (most recent call last):'):
                    idx=i
                    break
            if idx is not None:
                tb='\\n'.join(all_lines[idx:idx+8])
            else:
                err_lines=[l for l in all_lines if ('Error' in l or 'Exception' in l or 'FAILED' in l or 'E   ' in l)]
                tb='\\n'.join(err_lines[:8])
        results.append({'command':cmd_str,'exit_code':p.returncode,'key_result':key,'traceback_head':tb})
    except subprocess.TimeoutExpired as e:
        out=((e.stdout or '') + (e.stderr or '')) if isinstance(e.stdout,str) else ''
        lines=[ln for ln in out.splitlines() if ln.strip()]
        key='TIMEOUT'
        tb=''
        results.append({'command':cmd_str,'exit_code':'TIMEOUT','key_result':key,'traceback_head':tb})

print(json.dumps(results, indent=2))
