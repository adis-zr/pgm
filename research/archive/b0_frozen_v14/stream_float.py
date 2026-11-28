"""Native certified binary64 counterpart to stream.py's exact reference.

Per-node invariant: (1-u)^E * exact <= computed <= (1+u)^E * exact,
with source E=1, addition max(E)+1 and multiplication sum(E)+1.
Stable current-leaf product trees make Gray transitions independent of previous
rounding errors. Every arithmetic output is checked for normal range and the
FP environment is checked before entry and periodically. For r=Nhat/Zhat and
 delta=(E_N+E_Z)u < 1/2, exact normalized p is in
 [(1-delta)r, r/(1-delta)], evaluated as exact Fractions.
The C++ arithmetic implementation is part of the qualified trusted boundary;
this is not an independent numerical proof from an untrusted producer.
"""
from fractions import Fraction as F
from pathlib import Path
import ctypes as C
import time,subprocess,hashlib,math,sys,json,os
import stream

U=F(1,2**53)
BASE=Path(__file__).resolve().parent
LIB=BASE/'libstream_kernel.so'
FLAGS=['-O3','-std=c++17','-shared','-fPIC','-fno-fast-math','-ffp-contract=off','-frounding-math']
class RangeError(ValueError):
 def __init__(self,message,stats=None):
  super().__init__(message); self.stats=dict(stats or {})

def build(deadline=None):
 src=BASE/'stream_kernel.cpp'; record=BASE/'stream_build.json'
 stream._check(deadline, {'phase':'native_build'})
 sh=hashlib.sha256(src.read_bytes()).hexdigest()
 previous={}
 if record.exists():
  try:previous=json.loads(record.read_text())
  except (ValueError,OSError):pass
 binary_sha=hashlib.sha256(LIB.read_bytes()).hexdigest() if LIB.exists() else None
 if previous.get('source_sha256')!=sh or previous.get('compiler_flags')!=FLAGS or previous.get('binary_sha256')!=binary_sha or binary_sha is None:
  temp=LIB.with_name(LIB.name+'.tmp_'+str(os.getpid()))
  try:
   remaining=None if deadline is None else max(0.001,deadline-time.monotonic())
   p=subprocess.run([os.environ.get('CXX','g++'),*FLAGS,str(src),'-o',str(temp)],capture_output=True,text=True,timeout=remaining)   # HOST BUILD ADAPTER: the compiler is recorded in stream_build.json (Apple: g++ is clang)
   if p.returncode:raise RuntimeError(p.stderr)
   stream._check(deadline, {'phase':'native_build'})
   temp.replace(LIB)
  except subprocess.TimeoutExpired:
   raise stream.DeadlineExceeded({'phase':'native_build'})
  finally:temp.unlink(missing_ok=True)
  previous={'source_sha256':sh,'binary_sha256':hashlib.sha256(LIB.read_bytes()).hexdigest(),'compiler_flags':FLAGS}
  record.write_text(json.dumps(previous,indent=2)+'\n')
 stream._check(deadline, {'phase':'native_build'})
 return previous

def _load_verified(provenance,deadline=None):
 """Load an immutable hash-addressed path, never the replaceable build target.

 dlopen may cache a handle by pathname across recompilations. Giving each binary
 digest its own checked pathname binds the actual handle to reported bytes even
 after a second build (or module reload) in the same Python process.
 """
 stream._check(deadline, {'phase':'native_load'})
 digest=provenance['binary_sha256']
 if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
  raise RuntimeError('invalid binary identity')
 cache=BASE/'native_cache';cache.mkdir(exist_ok=True)
 path=cache/('stream_'+digest+'.so')
 if not path.exists():
  binary=LIB.read_bytes()
  if hashlib.sha256(binary).hexdigest()!=digest:
   raise RuntimeError('native binary changed between build and load')
  temp=path.with_name(path.name+'.tmp_'+str(os.getpid()))
  try:
   temp.write_bytes(binary);temp.replace(path)
  finally:temp.unlink(missing_ok=True)
 if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
  raise RuntimeError('hash-addressed native binary failed identity check')
 stream._check(deadline, {'phase':'native_load'})
 lib=C.CDLL(str(path))
 provenance['loaded_binary_path']=str(path)
 provenance['loader_binding']='immutable binary SHA256 pathname; bytes verified before dlopen'
 return lib

def _convert(q):
 try:x=float(q)
 except OverflowError:raise RangeError('source conversion overflow')
 if q==0:
  if x!=0:raise AssertionError('zero conversion')
  return x
 if not math.isfinite(x) or x<2*sys.float_info.min or x>sys.float_info.max/2:
  raise RangeError('source conversion range')
 if not (1-U)*q<=F(x)<=(1+U)*q:raise AssertionError('source relative conversion bound')
 return x

def solve(model,deadline=None):
 impl=time.get_clock_info('monotonic').implementation
 if not ((sys.platform.startswith('linux') and 'CLOCK_MONOTONIC' in impl) or (sys.platform=='darwin' and 'mach_absolute_time' in impl)):
  raise stream.UnsupportedError('native shared absolute clock contract requires Linux CLOCK_MONOTONIC or Apple mach_absolute_time (=CLOCK_UPTIME_RAW); host: %s' % impl)   # HOST CLOCK ADAPTER (shared by both arms)
 start=time.monotonic();build_start=time.monotonic(); provenance=build(deadline);lib=_load_verified(provenance,deadline);build_s=time.monotonic()-build_start
 stats={'solver':'certified_binary64_product_tree_stream','build_s':build_s,
        'configurations':0,'adds':0,'mults':0,'tree_updates':0,'source_conversions_checked':0,
        'recognition_s':0.0,'conversion_s':0.0,'execution_s':0.0,'publication_s':0.0}
 cards,ev,unary,edges,graph,comps=stream._prepare(model,deadline,stats)
 stats['recognition_s']=time.monotonic()-start-build_s
 fn=lib.stream_run
 dp=C.POINTER(C.c_double);ip=C.POINTER(C.c_uint64)
 fn.argtypes=[C.c_int,C.c_int,dp,dp,dp,C.c_double,dp,ip,dp,ip,ip];fn.restype=C.c_int
 ans=[None]*len(cards);intervals=[None]*len(cards);certs=[]
 for v,a in ev.items():
  ans[v]=[F(int(j==a)) for j in range(cards[v])];intervals[v]=[(p,p) for p in ans[v]]
 for aa,bb in comps:
  stream._check(deadline,stats)
  if len(aa)>=63:raise stream.UnsupportedError('native configuration counter exceeds 62 conditioned variables')
  m,n=len(aa),len(bb)
  # Guard every int expression in the C ABI and price native buffers before allocation.
  if n>2**28 or m*n>(2**31-1)//4:
   raise stream.UnsupportedError('native table indexing dimension limit')
  treebase=1
  while treebase<m+1:treebase*=2
  event_bound=(2*n+1)*(2*treebase)+(1<<m)*((2*n+1)*(treebase.bit_length()+1)+8*n+2*m+8)
  stats['native_event_counter_bound']=max(stats.get('native_event_counter_bound',0),event_bound)
  if event_bound>=1<<64:
   raise stream.UnsupportedError('native event counter bound exceeds uint64; exact route remains available')
  native_bound=2*n*(2*treebase*16+128)+4*m*n*8+256*(m+n+1)
  stats['native_allocation_bound_bytes']=max(stats.get('native_allocation_bound_bytes',0),native_bound)
  if native_bound>512*1024*1024:
   raise stream.UnsupportedError('native working-buffer reservation exceeds 512 MiB; exact route remains available')
  convstart=time.monotonic();aidx={v:i for i,v in enumerate(aa)};bidx={v:i for i,v in enumerate(bb)}
  def cvtable(xs):
   scale=max(xs)
   if not scale:raise ValueError('zero component unary mass')
   try:result=[_convert(F(x,scale)) for x in xs]
   except RangeError as ex:
    stats['elapsed_s']=time.monotonic()-start;ex.stats=dict(stats);raise
   stats['source_conversions_checked']+=len(xs)
   return result
  phi=[x for v in aa for x in cvtable(unary[v])];rho=[x for v in bb for x in cvtable(unary[v])]
  psi=[1.0]*(4*len(aa)*len(bb))
  for a in aa:
   for b in graph[a]:
    tab=edges[min(a,b),max(a,b)]
    if a>b:tab=[tab[0],tab[2],tab[1],tab[3]]
    i,j=aidx[a],bidx[b];psi[4*(i*len(bb)+j):4*(i*len(bb)+j)+4]=cvtable(tab)
  stats['conversion_s']+=time.monotonic()-convstart
  def doubles(xs):return (C.c_double*max(1,len(xs)))(*xs)
  n=len(aa)+len(bb);nums=(C.c_double*n)();exps=(C.c_uint64*n)();z=C.c_double();ez=C.c_uint64();counts=(C.c_uint64*4)()
  p,r,s=doubles(phi),doubles(rho),doubles(psi)
  native_deadline=1e30 if deadline is None else deadline;t=time.monotonic()
  status=fn(len(aa),len(bb),p,r,s,native_deadline,nums,exps,C.byref(z),C.byref(ez),counts)
  stats['execution_s']+=time.monotonic()-t
  for k,value in zip(['configurations','adds','mults','tree_updates'],counts):stats[k]+=int(value)
  stats['elapsed_s']=time.monotonic()-start
  if status==2:raise stream.DeadlineExceeded(stats)
  if status:raise RangeError('native route refused: '+{1:'arithmetic range',3:'floating environment',4:'error exponent cap',5:'allocation failure',6:'native exception'}.get(status,str(status)),stats)
  if counts[0] != 1<<len(aa):raise AssertionError('incomplete native stream')
  if z.value<=0:raise ValueError('zero mass in a connected component')
  pubstart=time.monotonic();maxdelta=F(0)
  for i,v in enumerate(aa+bb):
   delta=(int(exps[i])+int(ez.value))*U;maxdelta=max(maxdelta,delta)
   if delta>=F(1,2):raise RangeError('roundoff enclosure unavailable',stats)
   ratio=F(nums[i])/F(z.value);lo=max(F(0),(1-delta)*ratio);hi=min(F(1),ratio/(1-delta))
   if not 0<=lo<=hi<=1:raise AssertionError('invalid enclosure')
   if hi-lo>F(1,100):raise RangeError('delivered width target unavailable',stats)
   p1=(lo+hi)/2
   ans[v]=[1-p1,p1];intervals[v]=[(1-hi,1-lo),(lo,hi)]
  stats['publication_s']+=time.monotonic()-pubstart
  certs.append({'conditioned':aa,'independent':bb,'normalizer_float':z.value,
                'normalizer_exponent':int(ez.value),'numerator_exponents':list(exps),
                'max_delta':str(maxdelta),'configurations':int(counts[0])})
 stats['elapsed_s']=time.monotonic()-start;stream._check(deadline,stats)
 return {'status':'CERTIFIED_INTERVAL','intervals':intervals,'points':ans,'stats':stats,
         'certificate':{'method':'current-leaf product trees, per-operation error exponents, runtime range guards',
                        'components':certs,'build':provenance,'independent_numeric_replay_performed':False,
                        'clock_contract':'Linux CLOCK_MONOTONIC absolute deadline from Python, checked before/during construction and stream and after completion; wrapper final deadline remains authoritative.',
                        'input_gauge':'Each exact merged unary/pair is divided by its positive maximum; these constants cancel from normalized marginals.',
                        'cost':'Source validation/clearing/graph recognition + exact gauge/conversion checks + O(m*n+(n*log(m+1)+m+n)*2**m) binary64 work per component + exact-rational publication. Dense missing-edge identity slots are charged O(m*n). External parser and separate verifier are caller costs.'}}
