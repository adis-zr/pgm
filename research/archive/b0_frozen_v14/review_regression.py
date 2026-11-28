"""Independent tiny regression controls for the post-review orchestration repair."""
from fractions import Fraction as F
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile,json,time,subprocess,signal,hashlib
import core,planning,evaluate,support,forest

def run():
 results={}
 with tempfile.TemporaryDirectory() as tmp:
  t=Path(tmp);inp=t/'inputs';inp.mkdir();(inp/'tiny.uai').write_text('MARKOV\n1\n2\n1\n1 0\n2\n1 1\n')
  def args(folder):return SimpleNamespace(input=str(inp),output=str(folder),cases=None,seconds=1,route='auto')
  out=t/'stale';out.mkdir();(out/'tiny.json').write_text('{"status":"COMPLETED"}')
  with patch.object(evaluate.subprocess,'Popen',side_effect=AssertionError('must refuse before launch')):
   try:evaluate.panel(args(out));raise AssertionError('stale output accepted')
   except ValueError as e:assert 'pre-existing' in str(e)
  results['preexisting_output_refused_before_launch']=True
  out=t/'failed';calls=[]
  class Failed:
   returncode=1
   def communicate(self,timeout=None):return '', 'synthetic worker failure'
  def make_failed(cmd,**kw):
   calls.append(kw);Path(cmd[cmd.index('--output')+1]).write_text('{"status":"COMPLETED"}')
   return Failed()
  with patch.object(evaluate.subprocess,'Popen',side_effect=make_failed),patch.object(evaluate.platform,'platform',return_value='mocked'):
   evaluate.panel(args(out))
  receipt=json.loads((out/'receipts.json').read_text())[0]
  assert receipt['status']=='INVALID_PROCESS_EXIT' and receipt['returncode']==1
  assert calls[0]['start_new_session'] is True
  results['nonzero_exit_completion_refused']=True
  out=t/'killed';kills=[]
  class TimedOut:
   returncode=-signal.SIGKILL;pid=424242
   def __init__(self):self.calls=0
   def communicate(self,timeout=None):
    self.calls+=1
    if self.calls==1:raise subprocess.TimeoutExpired('controlled worker',timeout)
    return '', ''
  with patch.object(evaluate.subprocess,'Popen',return_value=TimedOut()),patch.object(evaluate.os,'killpg',side_effect=lambda p,s:kills.append((p,s))),patch.object(evaluate.platform,'platform',return_value='mocked'):
   evaluate.panel(args(out))
  assert kills==[(424242,signal.SIGKILL)]
  receipt=json.loads((out/'receipts.json').read_text())[0]
  assert receipt['process_outcome']=='TIMEOUT_KILL' and receipt['status']!='COMPLETED'
  results['timeout_targets_owned_session_group']=True
 m={'cards':[2,2],'evidence':{},'factors':[{'scope':(0,),'values':[F(1,3),F(2,3)]},{'scope':(0,1),'values':[F(1),F(0),F(0),F(1)]}]}
 with patch.object(forest,'solve',side_effect=forest.UnsupportedError('controlled forest decline')):
  r=core.solve(m,deadline=time.monotonic()+3)
 assert r['points']==[[F(1,3),F(2,3)]]*2
 assert r['stats']['reduction']['aliases']==1
 assert r['stats']['root_discovery'][-1]['chosen']=='identity_source_dag'
 results['identity_DAG_survives_alias_reduction']=True
 r=core.solve(m,deadline=time.monotonic()+3,route='dag')
 assert r['points']==[[F(1,3),F(2,3)]]*2
 assert r['stats']['reduction']=={'not_attempted':'forced valid identity DAG'}
 assert r['stats']['components'][0]['route']=='dag'
 results['forced_DAG_executes_valid_source_identity']=True
 r=core.solve(m,deadline=time.monotonic()+3)
 assert r['stats']['components'][0]['route']=='forest'
 assert r['necessity']['intrinsic_optimality']=='MATCHED_IN_THEOREM_4_SCOPE_ONLY'
 assert 'fixed-domain/fixed-tolerance/word-input forest family' in r['necessity']['scope']
 assert r['stats']['components'][0]['stats']['independent_replay'] is True
 assert len(r['intervals'])==2 and all(len(row)==2 for row in r['intervals'])
 for row in r['intervals']:
  assert all(lo<=p<=hi for (lo,hi),p in zip(row,[F(1,3),F(2,3)]))
 results['forest_returns_all_rows_with_scoped_matching_and_replay']=True
 for fn in [lambda:planning.order_and_price(m,deadline=time.monotonic()-1),lambda:planning.price(m,[0,1],deadline=time.monotonic()-1)]:
  try:fn();raise AssertionError('expired discovery deadline ignored')
  except TimeoutError:pass
 results['initial_score_and_price_check_deadline']=True
 with patch.object(planning,'order_and_price',side_effect=TimeoutError('controlled optional deadline')),patch('geometry.discover',return_value=None):
  p=core._discover_component(m,time.monotonic()+3,route='support')
 assert p['order']==[0,1] and p['kind']=='support'
 r=core._execute_component(p,time.monotonic()+3)
 assert r['points']==[[F(1,3),F(2,3)]]*2
 results['optional_order_timeout_retains_complete_route']=True
 independent={'cards':[2,2],'evidence':{},'factors':[{'scope':(0,),'values':[F(1),F(2)]},{'scope':(1,),'values':[F(3),F(4)]}]}
 original=support.solve;calls=[]
 def once_then_stop(*a,**kw):
  calls.append(None)
  if len(calls)==2:raise support.ResourceStop('controlled stop',{'sentinel':42})
  return original(*a,**kw)
 with patch.object(support,'solve',side_effect=once_then_stop):
  try:core.solve(independent,deadline=time.monotonic()+3,route='support');raise AssertionError('controlled stop lost')
  except support.ResourceStop as e:
   assert len(e.stats['core_trace']['completed_components'])==1
   assert e.stats['last_attempt']['sentinel']==42
 results['stopped_cell_retains_completed_component_trace']=True
 base=Path(__file__).parent
 out={'checks':results,'all_pass':all(results.values()),'source_sha256':{n:hashlib.sha256((base/n).read_bytes()).hexdigest() for n in ['core.py','evaluate.py','planning.py','forest.py']}}
 (base/'REVIEW_REGRESSION_RESULTS.json').write_text(json.dumps(out,indent=2)+'\n')
 print(json.dumps(out,indent=2))
 return out
if __name__=='__main__':run()
