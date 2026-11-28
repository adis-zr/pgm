
# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import json,sys,collections,hashlib
from pathlib import Path
from fractions import Fraction as F
import pgm.algorithms.structural.core as core

def mar(path):
    ts=iter(path.read_text().split());assert next(ts)=='MAR';n=int(next(ts));rows=[]
    for _ in range(n):rows.append([F(next(ts)) for _ in range(int(next(ts)))])
    assert next(ts,None) is None
    return rows

def analyze(folder,baseline,inputdir):
    folder=Path(folder);baseline=Path(baseline)
    records=json.loads((folder/'receipts.json').read_text())
    env=json.loads((folder/'environment.json').read_text())
    if 'source_hashes_before' in env:
        assert env['source_unchanged'] and env['source_hashes_before']==env['source_hashes_after'], 'campaign code changed'
    old=[json.loads(x) for x in (baseline/'CORRECTION_R1/ANALYSIS/SCORES.jsonl').read_text().splitlines()]
    report=[]
    for receipt in records:
        p=folder/(receipt['case']+'.json');r=dict(receipt)
        if p.exists():
            assert hashlib.sha256(p.read_bytes()).hexdigest()==receipt['output_sha256'], 'output identity mismatch'
            d=json.loads(p.read_text())
        else:d={}
        model,binding=core.read_uai(Path(inputdir)/(receipt['case']+'.uai'))
        if 'binding' in d:assert d['binding']==binding, 'input identity mismatch'
        r['reason']=d.get('reason');r['exception_type']=d.get('exception_type')
        if receipt['status']=='COMPLETED':
            assert receipt['returncode']==0 and receipt['process_outcome']=='EXIT', 'unsuccessful process cannot publish a completion'
            assert receipt['wall_s']<=receipt['budget_s'], 'completion exceeded delivery budget'
            rows=[[(F(a),F(b)) for a,b in row] for row in d['intervals']];pts=[[F(x) for x in row] for row in d['points']]
            assert d['binding']==binding
            assert len(rows)==len(model['cards']) and len(pts)==len(model['cards'])
            assert all(len(row)==card and len(point)==card for row,point,card in zip(rows,pts,model['cards']))
            core.verify_output(rows,pts);r['serialized_contract_check']=True
            for v,a in model.get('evidence',{}).items():
                assert pts[v]==[F(int(i==a)) for i in range(model['cards'][v])]
                assert all(lo<=F(int(i==a))<=hi for i,(lo,hi) in enumerate(rows[v]))
            r['input_output_identity_and_shape_check']=True
            r['max_width']=float(max((b-a for row in rows for a,b in row),default=F(0)))
            r['components']=[dict(route=c['route'],variables=len(c['variables']),stats=c['stats']) for c in d['stats']['components']]
            r['reduction']=d['stats'].get('reduction')
            matches=[x for x in old if x['case']==receipt['case'] and x['status']=='CERTIFIED']
            matches.sort(key=lambda x:(x['arm']!='GENERAL_BIDI_COMPLETE_V3',-x['budget_s']))
            if matches:
                ref=matches[0];rp=baseline/ref['out_dir']/'output.MAR';rs=mar(rp)
                assert len(rows)==len(rs) and all(len(a)==len(b) for a,b in zip(rows,rs))
                excursion=max((max(F(0),lo-q,q-hi) for row,rr in zip(rows,rs) for (lo,hi),q in zip(row,rr)),default=F(0))
                tolerance=F(str(ref.get('delivered_max_width') or 0))+F(1,10**12)
                r['baseline_comparison']=dict(arm=ref['arm'],budget=ref['budget_s'],max_excursion=float(excursion),tolerance=float(tolerance),consistent=excursion<=tolerance,meaning='Consistency with previously certified numerical output; not independent exact truth or controlled speed comparison')
        report.append(r)
    summary=dict(cells=len(records),statuses=dict(collections.Counter(x['status'] for x in report)),total_receipt_wall_s=sum(x['wall_s'] for x in report),complete_cases=[x['case'] for x in report if x['status']=='COMPLETED'],reference_disagreements=[x['case'] for x in report if not x.get('baseline_comparison',{}).get('consistent',True)],records=report)
    (folder/'ANALYSIS.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items() if k!='records'},indent=2))

if __name__=='__main__':analyze(*sys.argv[1:])
