import hashlib,json,pathlib,shutil,datetime
ROOT=pathlib.Path(__file__).resolve().parents[1]
PKT=pathlib.Path('/workspace/scratch/226d1e4428b0/dgp9_review/records/DGP9_SPECTRAL_HEATBATH_CONTINUATION')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def add(name,mp,ep,cohort,source,extra=None):
 d=ROOT/'inputs'/cohort;d.mkdir(parents=True,exist_ok=True);m=d/(name+'.uai');e=pathlib.Path(str(m)+'.evid');shutil.copyfile(mp,m);shutil.copyfile(ep,e)
 return dict(name=name,model=str(m),evidence=str(e),model_sha256=sha(m),evidence_sha256=sha(e),cohort=cohort,source=source,**(extra or {}))
sel=json.loads((ROOT/'PANEL_SELECTION.json').read_text());inv=json.loads((ROOT/'INVENTORY.json').read_text());by={(x['case'],x['model_path']):x for x in inv['cases']}
rows=[]
for t in sel['selected']:
 i=by[t['case'],t['model_path']];rows.append(add(t['case'],ROOT/t['model_path'],ROOT/t['evidence_path'],'historical46',dict(url=i['source_url'],model_path=t['model_path'],evidence_path=t['evidence_path'],archive=i['archive']),dict(family=t['family'],canonical_model_sha256=t['canonical_model_sha256'],canonical_evidence_sha256=t['canonical_evidence_sha256'],structure=i['structure'])))
seen={(r['model_sha256'],r['evidence_sha256']) for r in rows}; ext=[];synth=[];dedup=[]
for t in json.loads((PKT/'PRESERVATION_13_MANIFEST.json').read_text())['tasks']:
 mp=PKT/t['packet_copy'];ep=pathlib.Path(str(mp)+'.evid'); assert sha(mp)==t['model_sha256']; assert sha(ep)==t['evid_sha256']
 if (sha(mp),sha(ep)) in seen:dedup.append(t['name']);continue
 cohort='structured_regression' if t['name'].startswith('G4_') else 'external_extension'
 r=add(t['name'],mp,ep,cohort,dict(kind='DGP9 shipped preservation input',source_manifest=str(PKT/'PRESERVATION_13_MANIFEST.json'),historical_original_path=t['model'],hash_verified=True))
 (synth if cohort=='structured_regression' else ext).append(r);seen.add((sha(mp),sha(ep)))
for name in ['Promedus_36']:
 mp=ROOT/'sources/uai2022_tuning/MAR'/f'{name}.uai';ep=pathlib.Path(str(mp)+'.evid')
 if (sha(mp),sha(ep)) not in seen:ext.append(add(name,mp,ep,'external_extension',dict(url='https://ics.uci.edu/~dechter/uaicompetition/2022/TuningBenchmarks/MAR.zip',model_path=str(mp.relative_to(ROOT)),evidence_path=str(ep.relative_to(ROOT)))))
 else:dedup.append(name)
dls=[]
for name in ['uai2022_tuning','uai2022_final']:
 p=ROOT/'sources'/f'{name}.zip';dls.append(dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size,url='https://ics.uci.edu/~dechter/uaicompetition/2022/'+('TuningBenchmarks' if 'tuning' in name else 'FinalBenchmarks')+'/MAR.zip'))
for p in sorted((ROOT/'sources/bnlearn').glob('*.bif.gz')):
 name=p.name[:-7];url=f'https://www.bnlearn.com/bnrepository/{"munin4" if name=="munin1" else name}/{name}.bif.gz';dls.append(dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size,url=url))
obj=dict(schema='EXTERNAL_BENCHMARK_INPUT_RECOVERY_V1',created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),selection_source_commit='5ae02ff',selection_script_sha256=sha(ROOT/'recovery_scripts/inventory.py'),bif_converter_sha256=sha(ROOT/'recovery_scripts/bif.py'),selection_note='Original deterministic CBI-EXTERNAL-48-v1 selector rerun verbatim on freshly downloaded official sources, no inference outcomes read. The historical frozen inventory itself was not present, so exact historical46 identity is independently checked only on overlapping packet inputs and the three hash-bound anchors. BIF conversion independently verifies every source CPT entry. All original singleton queries, including evidence variables.',tasks=rows,extensions=ext,synthetic_regressions=synth,historical_target_slots=48,missing_slots=sel['shortfalls'],extension_deduplicated_names=dedup,downloads=dls)
(ROOT/'BENCHMARK_INPUTS.json').write_text(json.dumps(obj,indent=2));print('historical',len(rows),'extensions',len(ext),'synthetic',len(synth),'missing',sel['shortfalls']);print([r['name'] for r in rows]);print('extensions',[r['name'] for r in ext])
