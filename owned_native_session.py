"""Launch a selected child suspended, assign private kill-on-close Job, then run.

No PID-based ownership decisions; original process and private Job handles stay
open through terminal evidence. All descendants are contained before execution.
"""
import ctypes as C,ctypes.wintypes as W,json,time,subprocess,os
from pathlib import Path
K=C.WinDLL('kernel32',use_last_error=True);SIZE=C.c_size_t;U64=C.c_ulonglong
class SA(C.Structure):_fields_=[('length',W.DWORD),('descriptor',W.LPVOID),('inherit',W.BOOL)]
class SI(C.Structure):_fields_=[('cb',W.DWORD),('reserved',W.LPWSTR),('desktop',W.LPWSTR),('title',W.LPWSTR),('x',W.DWORD),('y',W.DWORD),('xs',W.DWORD),('ys',W.DWORD),('xc',W.DWORD),('yc',W.DWORD),('fill',W.DWORD),('flags',W.DWORD),('show',W.WORD),('cbres',W.WORD),('res2',C.POINTER(W.BYTE)),('stdin',W.HANDLE),('stdout',W.HANDLE),('stderr',W.HANDLE)]
class PI(C.Structure):_fields_=[('process',W.HANDLE),('thread',W.HANDLE),('pid',W.DWORD),('tid',W.DWORD)]
class LIMIT(C.Structure):_fields_=[('process_time',C.c_longlong),('job_time',C.c_longlong),('flags',W.DWORD),('min_ws',SIZE),('max_ws',SIZE),('active_limit',W.DWORD),('affinity',SIZE),('priority',W.DWORD),('scheduling',W.DWORD)]
class IO(C.Structure):_fields_=[(n,U64) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
class EXT(C.Structure):_fields_=[('basic',LIMIT),('io',IO),('process_memory_limit',SIZE),('job_memory_limit',SIZE),('peak_process_memory',SIZE),('peak_job_memory',SIZE)]
class ACCOUNT(C.Structure):_fields_=[('user',C.c_longlong),('kernel',C.c_longlong),('period_user',C.c_longlong),('period_kernel',C.c_longlong),('page_faults',W.DWORD),('total_processes',W.DWORD),('active_processes',W.DWORD),('terminated_processes',W.DWORD)]
class ACCOUNTIO(C.Structure):_fields_=[('basic',ACCOUNT),('io',IO)]
K.CreateJobObjectW.argtypes=[W.LPVOID,W.LPCWSTR];K.CreateJobObjectW.restype=W.HANDLE
K.SetInformationJobObject.argtypes=[W.HANDLE,W.INT,W.LPVOID,W.DWORD];K.SetInformationJobObject.restype=W.BOOL
K.QueryInformationJobObject.argtypes=[W.HANDLE,W.INT,W.LPVOID,W.DWORD,W.LPVOID];K.QueryInformationJobObject.restype=W.BOOL
K.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE];K.AssignProcessToJobObject.restype=W.BOOL
K.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.POINTER(SA),W.DWORD,W.DWORD,W.HANDLE];K.CreateFileW.restype=W.HANDLE
K.CreateProcessW.argtypes=[W.LPCWSTR,W.LPWSTR,W.LPVOID,W.LPVOID,W.BOOL,W.DWORD,W.LPVOID,W.LPCWSTR,C.POINTER(SI),C.POINTER(PI)];K.CreateProcessW.restype=W.BOOL
K.ResumeThread.argtypes=[W.HANDLE];K.ResumeThread.restype=W.DWORD
K.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];K.WaitForSingleObject.restype=W.DWORD
K.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)];K.GetExitCodeProcess.restype=W.BOOL
K.TerminateProcess.argtypes=[W.HANDLE,W.UINT];K.TerminateProcess.restype=W.BOOL
K.TerminateJobObject.argtypes=[W.HANDLE,W.UINT];K.TerminateJobObject.restype=W.BOOL
K.CloseHandle.argtypes=[W.HANDLE];K.CloseHandle.restype=W.BOOL
def require(value):
    if not value:raise C.WinError(C.get_last_error())
def run_owned_job(argv,cwd,env,artifact,budget,cancellation_path=None):
    artifact=Path(artifact);artifact.mkdir(exist_ok=False);log=artifact/'stdout.log';record={'argv':argv,'cwd':str(cwd),'budget_seconds':budget,'ownership':'Original process handle plus private unnamed Job; child assigned suspended before any code executes; Job kill-on-close covers descendants.','status':'preparing'}
    job=K.CreateJobObjectW(None,None);require(job);pi=PI();out=None;stdin=None;start=time.monotonic();assigned=False
    def save():(artifact/'execution.json').write_text(json.dumps(record,indent=2)+'\n')
    try:
        limits=EXT();limits.basic.flags=0x2000;require(K.SetInformationJobObject(job,9,C.byref(limits),C.sizeof(limits)))
        security=SA(C.sizeof(SA),None,True)
        out=K.CreateFileW(str(log),0x40000000,3,C.byref(security),1,0x80,None);require(out not in (None,C.c_void_p(-1).value))
        stdin=K.CreateFileW('NUL',0x80000000,3,C.byref(security),3,0x80,None);require(stdin not in (None,C.c_void_p(-1).value))
        si=SI();si.cb=C.sizeof(si);si.flags=0x100;si.stdin=stdin;si.stdout=out;si.stderr=out
        command=C.create_unicode_buffer(subprocess.list2cmdline(argv));block=C.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(env.items(),key=lambda p:p[0].upper()))+'\0\0')
        require(K.CreateProcessW(argv[0],command,None,None,True,0x4|0x400|0x8000000,block,str(cwd),C.byref(si),C.byref(pi)))
        require(K.AssignProcessToJobObject(job,pi.process));assigned=True;record.update(pid=pi.pid,status='running',assigned_suspended=True);save()
        if K.ResumeThread(pi.thread)==0xffffffff:raise C.WinError(C.get_last_error())
        K.CloseHandle(pi.thread);pi.thread=None;last=0
        while K.WaitForSingleObject(pi.process,250)==258:
            elapsed=time.monotonic()-start
            if cancellation_path is not None and Path(cancellation_path).is_file():
                control=Path(cancellation_path)
                if control.stat().st_size>1024:raise ValueError('Cancellation control exceeds1024bytes')
                body=control.read_bytes();intent=json.loads(body)
                if not isinstance(intent,dict) or set(intent)-{'cancel','reason'} or not isinstance(intent.get('cancel'),bool):raise ValueError('Malformed cancellation control')
                if intent['cancel']:
                    reason=intent.get('reason','Operator requested test cancellation')
                    if not isinstance(reason,str) or len(reason)>256:raise ValueError('Invalid cancellation reason')
                    require(K.TerminateJobObject(job,130));K.WaitForSingleObject(pi.process,10000)
                    record.update(status='cancelled_by_owner_request',cancellation={'path':str(control),'sha256':__import__('hashlib').sha256(body).hexdigest(),'reason':reason,'authority':'Original private Job handle; no PID lookup or reattachment.'});break
            if budget is not None and elapsed>budget:
                require(K.TerminateJobObject(job,137));K.WaitForSingleObject(pi.process,10000);record['status']='deadline_terminated';break
            if elapsed-last>=30:
                last=elapsed;record.update(elapsed_seconds=round(elapsed,2),stdout_bytes=log.stat().st_size);save()
                # Progress transport is advisory; a closed tool output pipe must
                # not change the lifetime of the already-owned target Job.
                with (artifact/'progress.jsonl').open('a',encoding='utf-8') as progress:
                    progress.write(json.dumps({'elapsed_seconds':record['elapsed_seconds'],'stdout_bytes':record['stdout_bytes']})+'\n')
        code=W.DWORD();require(K.GetExitCodeProcess(pi.process,C.byref(code)))
        record.update(exit_code=code.value,elapsed_seconds=round(time.monotonic()-start,2),stdout_bytes=log.stat().st_size)
        if record['status']=='running':record['status']='terminal'
        ext=EXT();account=ACCOUNT()
        if K.QueryInformationJobObject(job,9,C.byref(ext),C.sizeof(ext),None):record.update(peak_process_family_commit_bytes=ext.peak_job_memory,peak_single_process_commit_bytes=ext.peak_process_memory)
        accounting_io=ACCOUNTIO()
        if K.QueryInformationJobObject(job,8,C.byref(accounting_io),C.sizeof(accounting_io),None):record['io_bytes']={n:getattr(accounting_io.io,n) for n in ('read_bytes','write_bytes','other_bytes')}
        if K.QueryInformationJobObject(job,1,C.byref(account),C.sizeof(account),None):record.update(family_cpu_seconds=(account.user+account.kernel)/1e7,job_total_processes=account.total_processes,job_active_processes_at_parent_exit=account.active_processes)
        if account.active_processes:
            require(K.TerminateJobObject(job,0));cleanup_deadline=time.monotonic()+5
            while time.monotonic()<cleanup_deadline:
                require(K.QueryInformationJobObject(job,1,C.byref(account),C.sizeof(account),None))
                if not account.active_processes:break
                time.sleep(.05)
            record['job_active_processes_after_cleanup']=account.active_processes
    except Exception as exc:
        record.update(status='supervisor_error',error=repr(exc))
        if pi.process:
            if assigned:K.TerminateJobObject(job,137)
            else:K.TerminateProcess(pi.process,137)
            K.WaitForSingleObject(pi.process,10000)
            if assigned:
                cleanup=ACCOUNT();until=time.monotonic()+5
                while time.monotonic()<until:
                    if not K.QueryInformationJobObject(job,1,C.byref(cleanup),C.sizeof(cleanup),None):
                        record['cleanup_query_error']=C.get_last_error();break
                    record['job_active_processes_after_cleanup']=cleanup.active_processes
                    if not cleanup.active_processes:break
                    time.sleep(.05)
            code=W.DWORD()
            if K.GetExitCodeProcess(pi.process,C.byref(code)):record['exit_code']=code.value
        raise
    finally:
        save()
        for handle in (pi.thread,pi.process,out,stdin,job):
            if handle and handle!=C.c_void_p(-1).value:K.CloseHandle(handle)
    return record
