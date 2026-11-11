"""Fresh-process evaluation with explicit timeout receipts and exact output checks."""
import argparse,json,os,sys,time,subprocess,hashlib,platform,resource,signal
from pathlib import Path
from fractions import Fraction
sys.set_int_max_str_digits(0)
import core

def jsonable(x):
    if isinstance(x,Fraction):return str(x)
    if isinstance(x,dict):return {str(k):jsonable(v) for k,v in x.items()}
    if isinstance(x,(tuple,list)):return [jsonable(v) for v in x]
    if isinstance(x,set):return sorted(jsonable(v) for v in x)
    return x

def worker(a):
    t=time.monotonic();out={'status':'STARTED','route_request':a.route}
    try:resource.setrlimit(resource.RLIMIT_AS,(3*1024**3,3*1024**3));out['memory_policy']='RLIMIT_AS 3 GiB (address space)'
    except (ValueError,OSError) as e:out['memory_policy']='RLIMIT_AS unavailable on this host (%s); the panel supervisor enforces 3 GiB by sampled process-tree RSS kill (labelled metric change, shared by both arms)'%e   # HOST MEMORY ADAPTER
    try:
        m,binding=core.read_uai(a.input);out['binding']=binding;out['parse_s']=time.monotonic()-t
        out.update(core.solve(m,deadline=a.deadline,route=a.route))
        core.verify_output(out['intervals'],out['points']);out['publication_check']=True
        if sum(__import__('math').log2(d) for d in m['cards'])<=12:
            truth=core.brute_force(m)
            assert all(lo<=p<=hi for row,ps in zip(out['intervals'],truth) for (lo,hi),p in zip(row,ps))
            out['independent_bruteforce_containment']=True
        pt=time.monotonic()
        out['intervals'],out['points']=core.publish(out['intervals'],out['points'])
        out['publication_s']=time.monotonic()-pt
        out['numerical_verification_scope']='qualified exact or outward arithmetic and independent tiny oracle controls; forest route includes fresh-source/opposite-traversal replay sharing its arithmetic; other routes have no independent per-case numerical replay'
        out['status']='COMPLETED'
    except Exception as e:
        out['status']='STOPPED';out['exception_type']=type(e).__name__;out['reason']=str(e)
        out['stop_stats']=getattr(e,'stats',None)
    out['worker_elapsed_s']=time.monotonic()-t;ru=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;out['peak_rss_kib']=ru//1024 if sys.platform=='darwin' else ru;out['peak_rss_bytes']=ru if sys.platform=='darwin' else ru*1024   # HOST ADAPTER: ru_maxrss is bytes on Darwin, KiB on Linux
    Path(a.output).write_text(json.dumps(jsonable(out),indent=2))

def panel(a):
    dest=Path(a.output);dest.mkdir(parents=True,exist_ok=True)
    if (dest/'receipts.json').exists():raise ValueError('refuse to overwrite an existing campaign')
    base=Path(__file__).resolve().parent
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(base.iterdir()) if p.is_file() and p.suffix in ('.py','.cpp','.so')}
    paths=sorted(Path(a.input).glob('*.uai'))
    if a.cases:paths=[p for p in paths if p.stem in a.cases.split(',')]
    if any((dest/(p.stem+'.json')).exists() for p in paths):raise ValueError('refuse pre-existing case outputs')
    receipts=[]
    for p in paths:
        out=dest/(p.stem+'.json');start=time.monotonic()
        command=[sys.executable,str(Path(__file__).resolve()),'--worker','--input',str(p),'--output',str(out),'--route',a.route,'--deadline',str(start+a.seconds)]
        proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        # HOST MEMORY ADAPTER (shared by both arms): a watchdog thread samples the owned process tree's RSS every 50 ms and SIGKILLs the session group above the cap
        # (RLIMIT_AS cannot be lowered on this host); the main thread keeps the original communicate(timeout) semantics (budget + 1 s grace -> TIMEOUT_KILL)
        import threading;mem_cap=int(getattr(a,'mem_gib',3.0)*1024**3);watch={'peak':0,'killed':False,'stop':False}
        def watchdog():
            try:import psutil
            except ImportError:return
            while not watch['stop']:
                try:pr=psutil.Process(proc.pid);rss=pr.memory_info().rss+sum(c.memory_info().rss for c in pr.children(recursive=True))
                except Exception:return
                watch['peak']=max(watch['peak'],rss)
                if rss>mem_cap:
                    watch['killed']=True
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except Exception:pass
                    return
                time.sleep(0.05)
        th=threading.Thread(target=watchdog,daemon=True);th.start()
        try:stdout,stderr=proc.communicate(timeout=a.seconds+1);kind='EXIT'
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate();kind='TIMEOUT_KILL'
        watch['stop']=True;th.join(timeout=1.0)
        if watch['killed']:kind='MEMORY_KILL'
        peak_tree=watch['peak']
        wall=time.monotonic()-start
        data=json.loads(out.read_text()) if out.exists() else {}
        status=data.get('status','NO_OUTPUT')
        if proc.returncode!=0 and status=='COMPLETED':status='INVALID_PROCESS_EXIT'
        if status=='COMPLETED' and wall>a.seconds:status='LATE_OUTPUT'
        if kind=='MEMORY_KILL':status='MEMORY_KILL'
        rec=dict(case=p.stem,budget_s=a.seconds,wall_s=wall,status=status,process_outcome=kind,returncode=proc.returncode,peak_tree_rss_bytes_sampled=peak_tree,memory_cap_bytes=mem_cap,stderr=stderr[-2000:],output_sha256=hashlib.sha256(out.read_bytes()).hexdigest() if out.exists() else None)
        receipts.append(rec);(dest/'receipts.json').write_text(json.dumps(receipts,indent=2))
        print(p.stem,status,round(wall,3),flush=True)
    after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(base.iterdir()) if p.is_file() and p.suffix in ('.py','.cpp','.so')}
    (dest/'environment.json').write_text(json.dumps(dict(python=sys.version,platform=platform.platform(),machine=platform.machine(),cpu_count=os.cpu_count(),route=a.route,seconds=a.seconds,source_hashes_before=hashes,source_hashes_after=after,source_unchanged=hashes==after),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--deadline',type=float);p.add_argument('--mem-gib',type=float,default=3.0);p.add_argument('--seconds',type=float,default=20);p.add_argument('--route',default='auto',choices=['auto','dag','support','stream']);p.add_argument('--cases');a=p.parse_args()
    worker(a) if a.worker else panel(a)
