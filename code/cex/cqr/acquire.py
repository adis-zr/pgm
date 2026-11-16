"""EXTERNAL INPUT ACQUISITION for the CQR benchmark (metadata-only; no inference, no solver, no timing).

Standard library + the repo's UAI reader (cex/newarm/core.py read_uai) + cex/cqr/wcnf.py.

Sub-commands (each is re-derivable from the downloaded bytes):
    downloads     -> external/DOWNLOADS.json            (sha256/md5/bytes of every retrieved file + ledger receipt job)
    uai-inventory -> external/UAI2022_FINAL_MAR_INVENTORY.json
    uai-select    -> external/UAI2022_SELECTION.json    (16 slots)
    mc-inventory  -> external/MC2024_TRACK2_INVENTORY.json
    mc-select     -> external/MC2024_SELECTION.json     (8 slots)
    convert       -> external/wmc_uai/<name>.uai (+ .evid, .conversion.json) for the selected WMC instances; synthetic tests
    all           -> everything above in order

SELECTION RULES (fixed before any timing; SALT = sha256 of the received prompt file):
  UAI 2022 FINAL MAR
    family(name)  = maximal prefix of the file stem (".uai" removed) made of characters that are not a digit, '_' or '-';
                    if that prefix is empty (stem starts with a digit: the 4-character PDB-style protein ids) family = 'LEADING_DIGIT'.
    strata        = binary (all cards == 2) / nonbinary  x  max NONCONSTANT factor arity <= 2 / > 2  x  zero-free / contains-zero.
    dedup         = (i) byte sha256 of the .uai, (ii) normalized identity (see normalized_identity), (iii) legacy: byte or
                    normalized match (model-only or model+evidence) against the 46 legacy inputs of the frozen dev manifest.
    buckets       = within a stratum, median of .uai file bytes (statistics.median); lower = bytes <= median, upper = bytes > median.
    order         = sha256(SALT + '|' + byte_sha256) ascending (hex string comparison).
    fill          = strata enumerated in the fixed order below, lower bucket before upper; in each bucket the first candidate in
                    salted order whose family has < 2 selections so far (greedy, sequential, across all 16 slots) is taken;
                    otherwise the slot is UNAVAILABLE_* (never filled from another stratum; no round-robin applied).
  MC 2024 Track 2 (nonnegative WMC)
    pool          = instances with weight_status OK and odd index (the originally private final-evaluation instances);
                    even instances are used only if the odd pool cannot fill a bucket (recorded).
    family        = organizer family when the instance's content matches a collected-set instance after removing the
                    'c file' line, else 'UNMAPPED:<instance>' (instance-level row).  Cap: < 2 selections per family.
    buckets       = median of uncompressed CNF bytes over the pool; lower = bytes <= median, upper = bytes > median; 4 per bucket.
    order         = sha256(SALT + '|' + cnf_sha256) ascending.
    conversion    = selected instances with converted_table_entries <= CONVERSION_CAP are converted (exact OR-gate encoding);
                    larger ones keep the selection but the converted representation is UNAVAILABLE_CONVERSION_CAP.
"""
from __future__ import annotations
import argparse, glob, hashlib, json, lzma, os, re, statistics, sys, time
from fractions import Fraction
from itertools import product

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(CODE, 'cex', 'newarm'))
sys.path.insert(0, HERE)
from core import read_uai          # the repo's reader
import wcnf

SALT = '9ad09647fa9ee82e18e308fd6c5171b26f048b4891204b6446b54087b7508b31'
EXT = os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'CQR_2026-11-15', 'external')
LEDGER = os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'CQR_2026-11-15', 'CQR_LEDGER.jsonl')
LEGACY_INPUTS = '/Users/adis/Workspace/pgm/docs/handoff-received-2026-11-11-certified-executor/packet/inputs'
LEGACY_MANIFEST = os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'PAC_REPAIR_2026-11-13', 'admission_v6', 'manifest_full_dev_v42', 'CAMPAIGN_MANIFEST_dev.json')
CONVERSION_CAP = 50_000_000
STRATUM_ORDER = [(b, a, z) for b in ('binary', 'nonbinary') for a in ('arity<=2', 'arity>2') for z in ('zero-free', 'contains-zero')]

DOWNLOADS = [  # name (= receipt job suffix), local file, url, published md5 (None when none is published)
    ('uai2022_final_mar_zip', 'MAR.zip', 'https://ics.uci.edu/~dechter/uaicompetition/2022/FinalBenchmarks/MAR.zip', None),
    ('mc2024_track2_competition_tar', 'mc2024-track2-wmc_competition.tar', 'https://zenodo.org/api/records/14249068/files/mc2024-track2-wmc_competition.tar/content', '1c7e6279eaf29bf3731cebe07eedf107'),
    ('mc2024_track2_collected_tar', 'mc2024-track2-wmc_collected.tar', 'https://zenodo.org/api/records/14969231/files/mc2024-track2-wmc_collected.tar/content', '5c13508b51c6d4beaa7c611d4bb2cfa0'),
    ('dis_zip', 'DIS.zip', 'https://ics.uci.edu/~dechter/softwares/DIS.zip', None),
    ('zenodo_record_14249068_json', 'zenodo_record_14249068.json', 'https://zenodo.org/api/records/14249068', None),
    ('zenodo_record_14969231_json', 'zenodo_record_14969231.json', 'https://zenodo.org/api/records/14969231', None),
    ('uai2022_benchmarks_page_html', 'uaicompetition_uci-2022_results_benchmarks.html', 'https://uaicompetition.github.io/uci-2022/results/benchmarks/', None),
    ('mc2024_description_page', 'mccompetition_2024_mc_description.html', 'https://mccompetition.org/2024/mc_description', None),
]


def sha256_file(path):
    h = hashlib.sha256(); m = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk); m.update(chunk)
    return h.hexdigest(), m.hexdigest()


def utc():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def dump(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f, indent=1, sort_keys=False)
    print('wrote', os.path.relpath(path, CODE), os.path.getsize(path), 'bytes')


def ledger_records(scope='cqr_acquisition'):
    out = []
    if not os.path.exists(LEDGER):
        return out
    for line in open(LEDGER):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get('scope') == scope:
            out.append(r)
    return out


# ----------------------------------------------------------------------------------------------------------------------
def cmd_downloads(a):
    recs = ledger_records(); receipts = [r for r in recs if r.get('kind') == 'RECEIPT']
    rows = []
    for name, fn, url, md5pub in DOWNLOADS:
        p = os.path.join(EXT, 'downloads', fn)
        if not os.path.exists(p):
            rows.append(dict(name=name, file=fn, url=url, status='MISSING')); continue
        sha, md5 = sha256_file(p)
        jobs = [r for r in receipts if r['job'] in ('acquisition:' + name, 'acquisition:' + name + '_resume')]
        row = dict(name=name, file=os.path.relpath(p, CODE), url=url, bytes=os.path.getsize(p), sha256=sha, md5=md5,
                   md5_published=md5pub, md5_matches_published=(None if md5pub is None else md5 == md5pub),
                   retrieval_utc=[r['end_utc'] for r in jobs], receipt_jobs=[dict(job=r['job'], jid=r['jid'], outcome=r['outcome'], returncode=r.get('returncode'), wall_s=r.get('wall_s')) for r in jobs])
        if name == 'mc2024_track2_competition_tar':
            part = p + '.partial1'
            if os.path.exists(part):
                psha, pmd5 = sha256_file(part)
                row['first_attempt'] = dict(note='first curl attempt ended with curl exit 18 (transfer closed with 36874156 bytes remaining); the partial file was preserved as .partial1 and the transfer was RESUMED (curl -C -) under a second supervised job; the final bytes match the published md5',
                                            partial_bytes=os.path.getsize(part), partial_sha256=psha, partial_md5=pmd5)
        rows.append(row)
    # the Zenodo record JSONs carry the published checksums: verify both tars against them
    zen = {}
    for rid in ('14249068', '14969231'):
        p = os.path.join(EXT, 'downloads', 'zenodo_record_%s.json' % rid)
        if os.path.exists(p):
            d = json.load(open(p))
            zen[rid] = dict(doi=d.get('doi'), title=d['metadata'].get('title'), publication_date=d['metadata'].get('publication_date'),
                            files={f['key']: dict(size=f.get('size'), checksum=f.get('checksum')) for f in d.get('files', [])})
    for row in rows:
        for rid, z in zen.items():
            f = z['files'].get(row.get('file', '').split('/')[-1])
            if f:
                row['zenodo_record'] = rid; row['zenodo_size'] = f['size']; row['zenodo_checksum'] = f['checksum']
                row['zenodo_size_matches'] = (f['size'] == row['bytes']); row['zenodo_md5_matches'] = (f['checksum'] == 'md5:' + row['md5'])
    # DIS.zip content listing (hash only; not built)
    import zipfile
    dis = os.path.join(EXT, 'downloads', 'DIS.zip')
    dis_listing = [dict(name=i.filename, bytes=i.file_size) for i in zipfile.ZipFile(dis).infolist()] if os.path.exists(dis) else None
    out = dict(schema='CQR_EXTERNAL_DOWNLOADS_V1', generated_utc=utc(), salt_sha256_of_prompt=SALT, ledger=os.path.relpath(LEDGER, CODE), scope='cqr_acquisition',
               downloads=rows, zenodo_records=zen, dis_zip_listing=dis_listing, dis_note='DIS author code downloaded and hashed only; NOT built, NOT run',
               receipts_all=[dict(job=r['job'], outcome=r['outcome'], wall_s=r.get('wall_s'), returncode=r.get('returncode'), start_utc=r.get('start_utc'), end_utc=r.get('end_utc')) for r in receipts])
    dump(os.path.join(EXT, 'DOWNLOADS.json'), out)


# ----------------------------------------------------------------------------------------------------------------------
# UAI metadata

def family_of(stem):
    """maximal prefix of characters that are not digit/'_'/'-' ; empty -> 'LEADING_DIGIT'"""
    m = re.match(r'^[^0-9_\-]*', stem)
    pre = m.group(0) if m else ''
    return pre if pre else 'LEADING_DIGIT'


def canonical_factor(scope, values, cards):
    """sort the scope and permute the row-major table accordingly; values -> exact rational strings"""
    order = sorted(range(len(scope)), key=lambda i: scope[i])
    sscope = [scope[i] for i in order]
    if order == list(range(len(scope))):
        return sscope, [str(v) for v in values]
    strides = [0] * len(scope); s = 1
    for i in range(len(scope) - 1, -1, -1):
        strides[i] = s; s *= cards[scope[i]]
    out = []
    for xs in product(*(range(cards[v]) for v in sscope)):
        idx = 0
        for j, i in enumerate(order):
            idx += strides[i] * xs[j]
        out.append(str(values[idx]))
    return sscope, out


def normalized_identity(model):
    """sha256 of canonical JSON of (cards, sorted canonical factors, sorted evidence pairs); also the model-only hash"""
    cards = model['cards']
    facs = sorted((canonical_factor(f['scope'], f['values'], cards) for f in model['factors']), key=lambda t: (t[0], t[1]))
    body = json.dumps(dict(cards=cards, factors=facs), separators=(',', ':'))
    hm = hashlib.sha256(body.encode()).hexdigest()
    ev = sorted(model.get('evidence', {}).items())
    hme = hashlib.sha256((body + json.dumps(dict(evidence=ev), separators=(',', ':'))).encode()).hexdigest()
    return hm, hme


def uai_metadata(path):
    raw = open(path, 'rb').read(); kind = raw.split(None, 1)[0].decode()
    model, info = read_uai(path)
    cards = model['cards']; n = len(cards); fs = model['factors']
    max_ar = 0; max_nc = 0; has_zero = False; entries = 0; n_const = 0
    for f in fs:
        k = len(f['scope']); max_ar = max(max_ar, k); vs = f['values']; entries += len(vs)
        if any(v == 0 for v in vs):
            has_zero = True
        if all(v == vs[0] for v in vs):
            n_const += 1
        else:
            max_nc = max(max_nc, k)
    hm, hme = normalized_identity(model)
    epath = path + '.evid'
    stem = os.path.basename(path)[:-4]
    return dict(name=stem, model_path=path, evidence_path=epath, evidence_file_present=os.path.exists(epath), kind=kind, n_vars=n,
                cardinalities_min=min(cards), cardinalities_max=max(cards), binary=all(c == 2 for c in cards),
                n_factors=len(fs), n_constant_factors=n_const, max_arity_overall=max_ar, max_arity_nonconstant=max_nc,
                contains_zero=has_zero, total_table_entries=entries, file_bytes=len(raw), evidence_count=len(model['evidence']),
                evidence_bytes=os.path.getsize(epath) if os.path.exists(epath) else None,
                family=family_of(stem), byte_sha256=info['model_sha256'], evidence_sha256=info['evidence_sha256'],
                normalized_model_sha256=hm, normalized_model_evidence_sha256=hme)


def legacy_index():
    """byte / normalized hashes of the 46 legacy inputs (read-only; outside the worktree)"""
    out = {}
    for p in sorted(glob.glob(os.path.join(LEGACY_INPUTS, '*.uai'))):
        try:
            model, info = read_uai(p)
        except Exception as ex:   # noqa
            out[os.path.basename(p)] = dict(error=str(ex)[:100]); continue
        hm, hme = normalized_identity(model)
        out[os.path.basename(p)] = dict(byte_sha256=info['model_sha256'], normalized_model_sha256=hm, normalized_model_evidence_sha256=hme, evidence_count=len(model['evidence']))
    return out


def stratum_of(m):
    return ('binary' if m['binary'] else 'nonbinary', 'arity<=2' if m['max_arity_nonconstant'] <= 2 else 'arity>2', 'zero-free' if not m['contains_zero'] else 'contains-zero')


def cmd_uai_inventory(a):
    d = os.path.join(EXT, 'uai2022_mar'); files = sorted(glob.glob(os.path.join(d, '*.uai')))
    evids = sorted(glob.glob(os.path.join(d, '*.evid')))
    rows = []; errors = []
    for p in files:
        try:
            rows.append(uai_metadata(p))
        except Exception as ex:   # noqa
            errors.append(dict(model_path=p, error='%s: %s' % (type(ex).__name__, str(ex)[:200])))
    leg = legacy_index(); leg_by_byte = {}; leg_by_nm = {}; leg_by_nme = {}
    for k, v in leg.items():
        if 'byte_sha256' in v:
            leg_by_byte.setdefault(v['byte_sha256'], []).append(k); leg_by_nm.setdefault(v['normalized_model_sha256'], []).append(k); leg_by_nme.setdefault(v['normalized_model_evidence_sha256'], []).append(k)
    # dedup inside the archive: first in filename order is kept
    seen_b = {}; seen_n = {}; seen_model = {}; removed = []
    for m in rows:
        m['dedup'] = []; m['flags'] = []
        m['task_byte_sha256'] = hashlib.sha256((m['byte_sha256'] + ':' + m['evidence_sha256']).encode()).hexdigest()
        if m['task_byte_sha256'] in seen_b:
            m['dedup'].append(dict(reason='BYTE_DUPLICATE_OF', of=seen_b[m['task_byte_sha256']]))
        elif m['normalized_model_evidence_sha256'] in seen_n:
            m['dedup'].append(dict(reason='NORMALIZED_DUPLICATE_OF', of=seen_n[m['normalized_model_evidence_sha256']]))
        elif m['byte_sha256'] in seen_model:
            m['flags'].append(dict(flag='SAME_MODEL_BYTES_DIFFERENT_EVIDENCE', of=seen_model[m['byte_sha256']], note='distinct MAR task (different evidence); KEPT'))
        seen_b.setdefault(m['task_byte_sha256'], m['name']); seen_n.setdefault(m['normalized_model_evidence_sha256'], m['name']); seen_model.setdefault(m['byte_sha256'], m['name'])
        lb = leg_by_byte.get(m['byte_sha256']); lme = leg_by_nme.get(m['normalized_model_evidence_sha256']); lm = leg_by_nm.get(m['normalized_model_sha256'])
        if lb:
            m['dedup'].append(dict(reason='LEGACY_BYTE_DUPLICATE', of=lb))
        elif lme:
            m['dedup'].append(dict(reason='LEGACY_NORMALIZED_MODEL_AND_EVIDENCE_DUPLICATE', of=lme))
        elif lm:
            m['dedup'].append(dict(reason='LEGACY_NORMALIZED_MODEL_DUPLICATE_DIFFERENT_EVIDENCE', of=lm))
        m['same_name_in_legacy'] = (m['name'] + '.uai') in leg
        m['eligible'] = not m['dedup']
        s = stratum_of(m); m['stratum'] = '|'.join(s)
        if m['dedup']:
            removed.append(dict(name=m['name'], reasons=m['dedup']))
    counts = {}
    for m in rows:
        if m['eligible']:
            counts[m['stratum']] = counts.get(m['stratum'], 0) + 1
    fam = {}
    for m in rows:
        fam.setdefault(m['family'], []).append(m['name'])
    out = dict(schema='CQR_UAI2022_FINAL_MAR_INVENTORY_V1', generated_utc=utc(), source_archive=os.path.relpath(os.path.join(EXT, 'downloads', 'MAR.zip'), CODE),
               archive_sha256=sha256_file(os.path.join(EXT, 'downloads', 'MAR.zip'))[0], extracted_dir=os.path.relpath(d, CODE),
               n_uai_files=len(files), n_evid_files=len(evids),
               evidence_naming='every model MAR/<name>.uai has MAR/<name>.uai.evid beside it in the archive (format "k v a v a ..."; "0" = no evidence); this is exactly model_path + ".evid" as cex/newarm/core.py read_uai expects',
               rules=dict(family="maximal prefix of the stem (without '.uai') of characters that are not [0-9_-]; empty prefix (stem starts with a digit: the 4-char PDB-style protein ids) -> 'LEADING_DIGIT'; note 'or_chain_*.fg' therefore maps to family 'or' and '*.wcsp' stems to 'bwt'/'myciel'/'queen'",
                          constant_factor='all table values equal (including all-zero tables)', max_arity_nonconstant='max scope size over non-constant factors (0 if all factors are constant)',
                          contains_zero='some table value == 0 in some factor (evidence not applied)',
                          normalized_identity='sha256 of canonical JSON {cards, factors} where each factor scope is sorted and its row-major table permuted to the sorted scope, values as exact Fraction strings, factors sorted by (scope, table); model+evidence variant appends sorted evidence pairs. Detects whitespace / factor-order / scope-permutation duplicates; NOT variable renumbering',
                          dedup='task identity = (model bytes, evidence bytes): first file in name order kept; a later model whose task_byte_sha256 = sha256(model_sha256:evidence_sha256) or whose normalized model+evidence identity repeats is removed; a model whose MODEL bytes repeat under DIFFERENT evidence is a distinct MAR task and is KEPT with flag SAME_MODEL_BYTES_DIFFERENT_EVIDENCE (a model-only byte rule would additionally remove the flagged rows; count reported); models whose byte / normalized identity (model+evidence, or model-only) matches a legacy input of the frozen dev manifest are removed as LEGACY_* (model-level: a legacy model under new evidence is still a legacy model)',
                          salted_order='sha256(SALT|byte_sha256) ascending; ties (same model bytes, different evidence) broken by sha256(SALT|evidence_sha256), then name',
                          legacy_inputs=LEGACY_INPUTS, legacy_manifest=os.path.relpath(LEGACY_MANIFEST, CODE), legacy_count=len(leg),
                          strata='binary (all cards==2)/nonbinary x max_arity_nonconstant<=2/>2 x zero-free/contains-zero'),
               removed=removed, flagged_same_model_different_evidence=[dict(name=m['name'], flags=m['flags']) for m in rows if m['flags']],
               archive_counts_per_stratum={'|'.join(s): sum(1 for m in rows if m['stratum'] == '|'.join(s)) for s in STRATUM_ORDER},
               eligible_counts_per_stratum={'|'.join(s): counts.get('|'.join(s), 0) for s in STRATUM_ORDER},
               families={k: len(v) for k, v in sorted(fam.items())}, parse_errors=errors, legacy_index=leg, models=rows)
    dump(os.path.join(EXT, 'UAI2022_FINAL_MAR_INVENTORY.json'), out)


def salted(h):
    return hashlib.sha256((SALT + '|' + h).encode()).hexdigest()


def select_uai(inv):
    """pure function of the inventory: returns the 16 slots (used by the CLI and by test_acquire.py)"""
    elig = [m for m in inv['models'] if m['eligible']]
    fam_count = {}; slots = []
    for s in STRATUM_ORDER:
        key = '|'.join(s); members = [m for m in elig if m['stratum'] == key]
        if not members:
            n_arch = sum(1 for m in inv['models'] if m['stratum'] == key)
            for b in ('lower', 'upper'):
                slots.append(dict(slot='%s|%s' % (key, b), stratum=key, bucket=b, status='UNAVAILABLE_STRATUM_EMPTY', candidates=0, archive_models_in_stratum=n_arch,
                                  note=('no model of the FINAL MAR archive falls in this stratum' if n_arch == 0 else
                                        '%d archive model(s) fall in this stratum but all were removed as legacy duplicates: %s' % (n_arch, [m['name'] for m in inv['models'] if m['stratum'] == key]))))
            continue
        med = statistics.median([m['file_bytes'] for m in members])
        for b in ('lower', 'upper'):
            cand = [m for m in members if (m['file_bytes'] <= med if b == 'lower' else m['file_bytes'] > med)]
            cand.sort(key=lambda m: (salted(m['byte_sha256']), salted(m['evidence_sha256']), m['name']))
            row = dict(slot='%s|%s' % (key, b), stratum=key, bucket=b, median_bytes=med, candidates=len(cand),
                       candidate_order=[dict(name=m['name'], family=m['family'], salted=salted(m['byte_sha256'])[:16]) for m in cand])
            if not cand:
                row['status'] = 'UNAVAILABLE_BUCKET_EMPTY'; slots.append(row); continue
            pick = next((m for m in cand if fam_count.get(m['family'], 0) < 2), None)
            if pick is None:
                row['status'] = 'UNAVAILABLE_FAMILY_CAP'; row['families_capped'] = sorted({m['family'] for m in cand}); slots.append(row); continue
            fam_count[pick['family']] = fam_count.get(pick['family'], 0) + 1
            row.update(status='SELECTED', name=pick['name'], family=pick['family'], model_path=pick['model_path'], evidence_path=pick['evidence_path'],
                       byte_sha256=pick['byte_sha256'], evidence_sha256=pick['evidence_sha256'], normalized_model_evidence_sha256=pick['normalized_model_evidence_sha256'],
                       salted_order_key=salted(pick['byte_sha256']), file_bytes=pick['file_bytes'], n_vars=pick['n_vars'], n_factors=pick['n_factors'],
                       max_arity_nonconstant=pick['max_arity_nonconstant'], evidence_count=pick['evidence_count'], kind=pick['kind'])
            slots.append(row)
    return slots


def cmd_uai_select(a):
    inv = json.load(open(os.path.join(EXT, 'UAI2022_FINAL_MAR_INVENTORY.json')))
    slots = select_uai(inv)
    sel = [s for s in slots if s['status'] == 'SELECTED']
    out = dict(schema='CQR_UAI2022_SELECTION_V1', generated_utc=utc(), salt=SALT, salt_provenance='sha256 of docs/handoff-received-2026-11-15-cqr/packet/CLAUDE_CQR_IMPLEMENTATION_AND_BENCHMARK_PROMPT.txt (listed in the packet SHA256SUMS.txt)',
               rule=__doc__.split('SELECTION RULES')[1].split('MC 2024')[0].strip(), target=16, selected=len(sel), unavailable=16 - len(sel),
               unavailable_breakdown={k: sum(1 for s in slots if s['status'] == k) for k in ('UNAVAILABLE_STRATUM_EMPTY', 'UNAVAILABLE_BUCKET_EMPTY', 'UNAVAILABLE_FAMILY_CAP')},
               round_robin_applied=False, round_robin_note='the predeclared metadata-only round-robin permitted by the note was NOT applied; deficits are left visible',
               family_counts_selected={f: sum(1 for s in sel if s['family'] == f) for f in sorted({s['family'] for s in sel})}, slots=slots)
    dump(os.path.join(EXT, 'UAI2022_SELECTION.json'), out)
    for s in slots:
        print(' ', s['slot'].ljust(44), s['status'], s.get('name', ''))


# ----------------------------------------------------------------------------------------------------------------------
# MC 2024 Track 2

def _strip_file_line_sha1(path):
    h = hashlib.sha1()
    with lzma.open(path, 'rb') as f:
        for line in f:
            if not line.startswith(b'c file'):
                h.update(line)
    return h.hexdigest()


def collected_families():
    """family descriptions from the organizer collected tar: {content_sha1_without_c_file_line: (family, inner_name)}"""
    base = os.path.join(EXT, 'mc2024_track2_collected'); out = {}; fams = []
    for sub in sorted(glob.glob(os.path.join(base, 'inner', '*'))):
        if not os.path.isdir(sub):
            continue
        fam = os.path.basename(sub)
        auth = open(os.path.join(sub, '00_authors.txt'), errors='replace').read().strip() if os.path.exists(os.path.join(sub, '00_authors.txt')) else None
        desc = open(os.path.join(sub, '00_description.txt'), errors='replace').read().strip() if os.path.exists(os.path.join(sub, '00_description.txt')) else None
        files = sorted(glob.glob(os.path.join(sub, '**', '*.cnf.xz'), recursive=True)) + sorted(glob.glob(os.path.join(sub, '**', '*.cnf'), recursive=True))
        fams.append(dict(family=fam, authors=auth, description=desc, n_instances=len(files), instances=[os.path.relpath(f, base) for f in files]))
        for f in files:
            out[_strip_file_line_sha1(f) if f.endswith('.xz') else hashlib.sha1(b''.join(l for l in open(f, 'rb') if not l.startswith(b'c file'))).hexdigest()] = (fam, os.path.relpath(f, base))
    return out, fams


def cmd_mc_inventory(a):
    comp = os.path.join(EXT, 'mc2024_track2_competition')
    files = sorted(glob.glob(os.path.join(comp, '*', '*.cnf.xz')))
    shas = {}
    for sf in glob.glob(os.path.join(comp, '*', 'shasums.txt')):
        for line in open(sf):
            parts = line.split()
            if len(parts) == 2:
                shas[os.path.basename(parts[1])] = parts[0]
    fam_map, fams = collected_families()
    rows = []
    for i, p in enumerate(files):
        name = os.path.basename(p)[:-len('.cnf.xz')]
        idx = int(re.search(r'_(\d+)$', name).group(1))
        t0 = time.monotonic()
        meta = wcnf.scan_wcnf(p)
        meta['parse_wall_s'] = round(time.monotonic() - t0, 3)
        # the organizers' shasums.txt lists sha1 of the UNCOMPRESSED .cnf -> verify
        h1 = hashlib.sha1()
        with lzma.open(p, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h1.update(chunk)
        key = _strip_file_line_sha1(p)
        fam = fam_map.get(key)
        row = dict(name=name, index=idx, odd_index=(idx % 2 == 1), originally_private=(idx % 2 == 1), cnf_xz_path=p, cnf_xz_bytes=os.path.getsize(p),
                   cnf_sha1_uncompressed=h1.hexdigest(), organizer_sha1=shas.get(name + '.cnf'), organizer_sha1_matches=(shas.get(name + '.cnf') == h1.hexdigest()),
                   family=(fam[0] if fam else 'UNMAPPED:' + name), family_mapped=bool(fam), collected_match=(fam[1] if fam else None),
                   selection_eligible=(meta['weight_status'] == 'OK' and meta['count_semantics_status'] == 'OK'), conversion_within_cap=(meta['converted_table_entries'] <= CONVERSION_CAP),
                   intake_refusal=(meta['weight_status'] if meta['weight_status'] != 'OK' else (meta['count_semantics_status'] if meta['count_semantics_status'] != 'OK' else None)))
        row.update(meta)
        rows.append(row)
        print('  %3d/%d %s n=%d m=%d maxk=%d bytes=%d %s %s type=%s show=%d' % (i + 1, len(files), name, meta['n_vars'], meta['m_header'], meta['max_clause_length_raw'], meta['cnf_bytes'], meta['weight_status'], meta['count_semantics_status'], meta['declared_type'], meta['show_lines']), flush=True)
    fmt = dict(observed='c t wmc / c file <name>.cnf / p cnf <n> <m> / c p weight <lit> <w> 0 (one line per literal; decimal weight strings) / clauses "<lit> ... 0" one per line',
               weight_lines_per_instance='2n for every instance (both literals of every variable)' if all(r['n_weight_lines'] == 2 * r['n_vars'] for r in rows) else 'VARIES (see rows)',
               both_literal_weights_all=all(r['both_literal_weights_given_for_all_vars'] for r in rows),
               normalized_exact_count=sum(1 for r in rows if r['normalized_exact_rational']), normalized_float64_count=sum(1 for r in rows if r['normalized_float64']),
               normalized_or_unit_exact_count=sum(1 for r in rows if r['normalized_or_unit_exact']), normalized_or_none_float64_count=sum(1 for r in rows if r['normalized_or_none_float64']),
               instances_with_unit_pairs=sum(1 for r in rows if r['vars_unit_pair_1_1']), instances_with_no_weight_line_vars=sum(1 for r in rows if r['vars_no_weight_line_at_all']),
               total_vars=sum(r['n_vars'] for r in rows), total_weighted_pairs=sum(r['vars_weighted_pairs'] for r in rows), total_unit_pairs=sum(r['vars_unit_pair_1_1'] for r in rows), total_no_weight_line_vars=sum(r['vars_no_weight_line_at_all'] for r in rows),
               weighted_pairs_not_normalized_float64=sum(r['vars_weighted_pair_not_normalized_float64'] for r in rows),
               clauses_with_repeated_literals=sum(r['clauses_with_repeated_literals'] for r in rows), instances_with_repeated_literal_clauses=sum(1 for r in rows if r['clauses_with_repeated_literals']),
               max_clause_length_over_3_instances=sum(1 for r in rows if r['max_clause_length_effective'] > 3),
               header_matches_all=all(r['header_matches'] for r in rows), refused=[r['name'] for r in rows if r['weight_status'] != 'OK'],
               mc2024_description_page_statement='Track 2 (no negative weights, only weights w_l + w_{not l} = 1 or none)',
               max_weight_digit_characters=max(r['max_weight_significant_digits'] for r in rows),
               note='weights are plain decimal strings (no exponent, no fraction form seen) of up to %d digit characters; "normalized" is reported both exactly (decimal sum == 1) and in float64' % max(r['max_weight_significant_digits'] for r in rows))
    out = dict(schema='CQR_MC2024_TRACK2_INVENTORY_V1', generated_utc=utc(), competition_tar=os.path.relpath(os.path.join(EXT, 'downloads', 'mc2024-track2-wmc_competition.tar'), CODE),
               competition_tar_sha256=sha256_file(os.path.join(EXT, 'downloads', 'mc2024-track2-wmc_competition.tar'))[0],
               collected_tar=os.path.relpath(os.path.join(EXT, 'downloads', 'mc2024-track2-wmc_collected.tar'), CODE),
               collected_tar_sha256=sha256_file(os.path.join(EXT, 'downloads', 'mc2024-track2-wmc_collected.tar'))[0],
               n_instances=len(rows), n_odd=sum(1 for r in rows if r['odd_index']), n_refused=sum(1 for r in rows if r['weight_status'] != 'OK'),
               n_organizer_sha1_matches=sum(1 for r in rows if r['organizer_sha1_matches']), format=fmt,
               family_mapping=dict(method="content match: sha1 of the instance text after removing the 'c file <name>' comment line, against every instance in the organizer collected tar",
                                   collected_families=fams, n_mapped=sum(1 for r in rows if r['family_mapped']), n_unmapped=sum(1 for r in rows if not r['family_mapped']),
                                   statement='the organizer Track-2 collected tar (1,218,560 bytes) contains ONE submission directory (labelled Track3_Set1_Auction, 10 instances, "No descriptions provided"); family mapping is therefore reconstructable only for the instances matching those 10 files; all other competition instances carry the anonymised name mc2024_track2-random_<idx> and are UNMAPPED -> instance-level rows'),
               conversion_cap_entries=CONVERSION_CAP, instances=rows)
    dump(os.path.join(EXT, 'MC2024_TRACK2_INVENTORY.json'), out)


def select_mc(inv):
    pool = [r for r in inv['instances'] if r['selection_eligible'] and r['odd_index']]
    even_pool = [r for r in inv['instances'] if r['selection_eligible'] and not r['odd_index']]
    med = statistics.median([r['cnf_bytes'] for r in pool]) if pool else None
    fam_count = {}; slots = []
    for b in ('lower', 'upper'):
        cand = [r for r in pool if (r['cnf_bytes'] <= med if b == 'lower' else r['cnf_bytes'] > med)]
        cand.sort(key=lambda r: salted(r['cnf_sha256']))
        taken = set()
        for j in range(4):
            row = dict(slot='%s|%d' % (b, j), bucket=b, median_bytes=med, candidates=len(cand), odd_pool=len(pool))
            pick = next((r for r in cand if r['name'] not in taken and fam_count.get(r['family'], 0) < 2), None); src = 'odd'
            if pick is None:
                ecand = sorted([r for r in even_pool if (r['cnf_bytes'] <= med if b == 'lower' else r['cnf_bytes'] > med)], key=lambda r: salted(r['cnf_sha256']))
                pick = next((r for r in ecand if r['name'] not in taken and fam_count.get(r['family'], 0) < 2), None); src = 'even_fallback'
            if pick is None:
                row['status'] = 'UNAVAILABLE_BUCKET_EMPTY'; slots.append(row); continue
            taken.add(pick['name']); fam_count[pick['family']] = fam_count.get(pick['family'], 0) + 1
            row.update(status='SELECTED', source_pool=src, name=pick['name'], index=pick['index'], odd_index=pick['odd_index'], family=pick['family'], family_mapped=pick['family_mapped'],
                       cnf_xz_path=pick['cnf_xz_path'], cnf_sha256=pick['cnf_sha256'], cnf_bytes=pick['cnf_bytes'], salted_order_key=salted(pick['cnf_sha256']),
                       n_vars=pick['n_vars'], m_header=pick['m_header'], max_clause_length=pick['max_clause_length_raw'], converted_table_entries=pick['converted_table_entries'],
                       converted_auxiliary_vars=pick['converted_auxiliary_vars'], conversion_within_cap=pick['conversion_within_cap'],
                       normalized_exact_rational=pick['normalized_exact_rational'], normalized_float64=pick['normalized_float64'])
            slots.append(row)
    return slots


def cmd_mc_select(a):
    inv = json.load(open(os.path.join(EXT, 'MC2024_TRACK2_INVENTORY.json')))
    slots = select_mc(inv); sel = [s for s in slots if s['status'] == 'SELECTED']
    out = dict(schema='CQR_MC2024_SELECTION_V1', generated_utc=utc(), salt=SALT, rule=__doc__.split('MC 2024 Track 2 (nonnegative WMC)')[1].strip(), target=8, selected=len(sel),
               family_level_claim_possible=False,
               coverage_deficit='4 families x 2 size buckets was NOT achievable: the organizer collected tar for Track 2 maps only %d/%d competition instances to one family (%s); the remaining instances are anonymised (mc2024_track2-random_<idx>) and are treated as instance-level rows. Selection = 2 size buckets x 4 by salted order over odd-index (originally private) instances with the family cap applied to the one mapped family.' % (inv['family_mapping']['n_mapped'], inv['n_instances'], ', '.join(f['family'] for f in inv['family_mapping']['collected_families'])),
               selection_bias_note='MC 2024 organizers discard instances solvable by standard solvers in < 10 s and keep at most 40 per source that common solvers cannot solve (mccompetition.org/2024/mc_description, "Benchmark Selection"); the competition set is intentionally hard-filtered, so a short-budget failure on it is evidence about hard-filtered instances, not universal ineffectiveness',
               prior_exposure_audit='grep over the worktree code/, runs/ and the docs/ handoff packets for "mc2024", "mccompetition", "track2-random", "14249068" found no occurrence outside this acquisition directory and the 2026-11-15 CQR handoff packet; these instances have not been used in this program before (audited 2026-11-15, not assumed)',
               odd_pool=len([r for r in inv['instances'] if r['selection_eligible'] and r['odd_index']]), even_fallback_used=any(s.get('source_pool') == 'even_fallback' for s in sel),
               conversion_cap_entries=CONVERSION_CAP, over_cap_selected=[s['name'] for s in sel if not s['conversion_within_cap']], slots=slots)
    dump(os.path.join(EXT, 'MC2024_SELECTION.json'), out)
    for s in slots:
        print(' ', s['slot'], s['status'], s.get('name', ''), s.get('family', ''), s.get('cnf_bytes', ''), 'cap_ok=%s' % s.get('conversion_within_cap', ''))


def cmd_convert(a):
    sel = json.load(open(os.path.join(EXT, 'MC2024_SELECTION.json'))); outdir = os.path.join(EXT, 'wmc_uai'); os.makedirs(outdir, exist_ok=True)
    tests = wcnf.selftest(os.path.join(outdir, 'synthetic_tests'), read_uai)
    print('synthetic tests:', [(t['test'], t['status']) for t in tests])
    results = []
    for s in sel['slots']:
        if s['status'] != 'SELECTED':
            continue
        name = s['name']; row = dict(slot=s['slot'], name=name, cnf_xz_path=s['cnf_xz_path'], cnf_sha256=s['cnf_sha256'], converted_table_entries=s['converted_table_entries'])
        if not s['conversion_within_cap']:
            row.update(status='UNAVAILABLE_CONVERSION_CAP', cap=CONVERSION_CAP, note='native CNF representation remains the only available representation of this selected instance')
            results.append(row); print(' ', name, row['status'], s['converted_table_entries']); continue
        up = os.path.join(outdir, name + '.uai'); t0 = time.monotonic()
        try:
            side = wcnf.convert(s['cnf_xz_path'], up, name=name, cap_entries=CONVERSION_CAP)
        except ValueError as ex:
            # the converter's refusal code is the message prefix: REFUSED_NEGATIVE_OR_NONRATIONAL_WEIGHT or REFUSED_PROJECTED_COUNT_SEMANTICS (CQR-10; 'c t pmc' / 'c t pwmc' / any 'c p show' line)
            code = str(ex).split(':', 1)[0].strip() if str(ex).startswith('REFUSED_') else 'REFUSED_NEGATIVE_OR_NONRATIONAL_WEIGHT'
            row.update(status=code, detail=str(ex)[:200]); results.append(row); print(' ', name, code); continue
        row.update(status='CONVERTED', uai_path=up, uai_sha256=side['uai_sha256'], uai_bytes=side['uai_bytes'], evid_path=up + '.evid', sidecar=up + '.conversion.json',
                   n_original_vars=side['n_original_vars'], n_auxiliary_vars=side['n_auxiliary_vars'], n_factors=side['n_factors'], table_entries=side['table_entries'],
                   missing_weights_defaulted=len(side['missing_weight_literals_defaulted_to_1']), conversion_wall_s=round(time.monotonic() - t0, 3))
        # certificate: full enumeration only for n <= 12 (no real instance qualifies: min n is recorded in the inventory);
        # pointwise check (not inference): a few random original assignments -> unique nonzero completion, product == CNF weight
        if side['n_original_vars'] <= 12:
            row['certificate'] = wcnf.certificate(s['cnf_xz_path'], up, read_uai)
        else:
            row['certificate'] = dict(status='NOT_APPLICABLE_N_GT_12', n_original_vars=side['n_original_vars'], note='full-enumeration certificate is defined for n <= 12 original variables; see synthetic tests')
        import random
        meta, clauses, weights = wcnf.scan_wcnf(s['cnf_xz_path'], keep_clauses=True)
        if side['table_entries'] <= 2_000_000:
            model, info = read_uai(up); reader = 'cex/newarm/core.py read_uai (exact Fraction tables)'
        else:
            model, info = wcnf.read_uai_light(up); reader = 'cex/cqr/wcnf.py read_uai_light (same token grammar, string tables; the repo reader is not round-tripped above 2,000,000 entries in this stage)'
        assert info['model_sha256'] == side['uai_sha256']
        rnd = random.Random(int(s['cnf_sha256'][:8], 16)); pts = [tuple(rnd.randint(0, 1) for _ in range(meta['n_vars'])) for _ in range(8)]
        row['pointwise_check'] = dict(assignments=wcnf.pointwise_check(model, meta['n_vars'], clauses, weights, pts, max_aux_flips=64, seed=int(s['cnf_sha256'][:8], 16)),
                                      aux_flips_per_assignment='all auxiliaries if <= 64 else a seeded sample of 64', reader=reader, uai_sha256_reader=info['model_sha256'],
                                      seed='int(cnf_sha256[:8],16)', status='PASS')
        results.append(row); print(' ', name, row['status'], side['n_total_vars'], 'vars', side['n_factors'], 'factors', side['table_entries'], 'entries', flush=True)
    out = dict(schema='CQR_WMC_CONVERSION_V1', generated_utc=utc(), cap_entries=CONVERSION_CAP, synthetic_tests=tests, conversions=results,
               rule=wcnf.__doc__)
    dump(os.path.join(EXT, 'wmc_uai', 'CONVERSION_RESULTS.json'), out)




# ----------------------------------------------------------------------------------------------------------------------
# report (every number re-derived from the JSON outputs and the ledger)

def cmd_report(a):
    J = lambda n: json.load(open(os.path.join(EXT, n)))
    dl = J('DOWNLOADS.json'); ui = J('UAI2022_FINAL_MAR_INVENTORY.json'); us = J('UAI2022_SELECTION.json')
    mi = J('MC2024_TRACK2_INVENTORY.json') if os.path.exists(os.path.join(EXT, 'MC2024_TRACK2_INVENTORY.json')) else None
    ms = J('MC2024_SELECTION.json') if os.path.exists(os.path.join(EXT, 'MC2024_SELECTION.json')) else None
    cv = J('wmc_uai/CONVERSION_RESULTS.json') if os.path.exists(os.path.join(EXT, 'wmc_uai', 'CONVERSION_RESULTS.json')) else None
    receipts = [r for r in ledger_records() if r.get('kind') == 'RECEIPT']
    charged = sum((r.get('wall_s') or 0.0) for r in receipts)
    other_scopes = {}
    for line in open(LEDGER):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get('kind') == 'RECEIPT' and r.get('scope') != 'cqr_acquisition':
            other_scopes[r['scope']] = other_scopes.get(r['scope'], 0) + 1
    L = []; w = L.append
    w('# CQR external input acquisition report (2026-11-15)\n')
    w('Scope: metadata-only acquisition of external inputs for the CQR benchmark. **No inference, no solver, no timing of any arm was run.** Every statement below is re-derived from the downloaded bytes by `cex/cqr/acquire.py` (this file is generated by its `report` sub-command); `cex/cqr/test_acquire.py` re-derives both selections from the inventories and asserts they match.\n')
    w('Worktree: `/Users/adis/Workspace/pgm-cqr-2026-11-15/code` (branch `cqr-2026-11-15`). Output root: `runs/mdi_2026-10-28/CQR_2026-11-15/external/`. Ledger: `runs/mdi_2026-10-28/CQR_2026-11-15/CQR_LEDGER.jsonl`, scope `cqr_acquisition`.\n')
    w('SALT for every hash order = `%s` = sha256 of `docs/handoff-received-2026-11-15-cqr/packet/CLAUDE_CQR_IMPLEMENTATION_AND_BENCHMARK_PROMPT.txt` (verified against the packet `SHA256SUMS.txt`); fixed before any timing.\n' % SALT)
    w('## 1. Retrieved and verified\n')
    w('| name | bytes | sha256 | md5 | published md5 / Zenodo check | receipt outcome(s) |\n|---|---|---|---|---|---|')
    for r in dl['downloads']:
        pub = '-' if r.get('md5_published') is None else ('MATCH' if r['md5_matches_published'] else 'MISMATCH')
        if r.get('zenodo_record'):
            pub += '; Zenodo size %s / md5 %s' % ('match' if r['zenodo_size_matches'] else 'MISMATCH', 'match' if r['zenodo_md5_matches'] else 'MISMATCH')
        w('| %s | %d | `%s` | `%s` | %s | %s |' % (r['name'], r['bytes'], r['sha256'], r['md5'], pub, ', '.join(j['outcome'] for j in r['receipt_jobs'])))
    comp = next(r for r in dl['downloads'] if r['name'] == 'mc2024_track2_competition_tar')
    if 'first_attempt' in comp:
        w('\nThe competition tar needed two supervised attempts: the first `curl` exited 18 after %d bytes (transfer closed by the server; receipt NONZERO_EXIT, partial preserved as `.partial1`, sha256 `%s`); the second attempt resumed with `curl -C -` and completed; the final file matches the published md5 and the Zenodo record size.' % (comp['first_attempt']['partial_bytes'], comp['first_attempt']['partial_sha256']))
    w('\nAlso saved as retrieved evidence: the Zenodo record JSONs for 14249068 and 14969231 (titles "%s" / "%s", publication dates %s / %s), the UAI 2022 benchmarks page (its FINAL MAR link resolves to `https://www.ics.uci.edu/~dechter/uaicompetition/2022/FinalBenchmarks/MAR.zip`; the Tuning archives are separate links and were NOT used), and the MC 2024 description page.' % (
        dl['zenodo_records']['14249068']['title'], dl['zenodo_records']['14969231']['title'], dl['zenodo_records']['14249068']['publication_date'], dl['zenodo_records']['14969231']['publication_date']))
    w('\nDIS.zip (author code) was downloaded and hashed only: contents %s. It was NOT built and NOT run.\n' % ', '.join('`%s` (%d B)' % (x['name'], x['bytes']) for x in dl['dis_zip_listing']))
    w('## 2. UAI 2022 FINAL MAR\n')
    w('Archive: %d `.uai` + %d `.evid` files under `MAR/`; all %d headers are `MARKOV` (no `BAYES` file in the FINAL MAR archive). Evidence naming: **`MAR/<name>.uai.evid` beside every model** (format `k v a v a ...`, `0` = no evidence) - exactly `model_path + ".evid"` as `cex/newarm/core.py read_uai` expects; files were extracted unchanged to `external/uai2022_mar/`. Parse errors: %d.\n' % (ui['n_uai_files'], ui['n_evid_files'], ui['n_uai_files'], len(ui['parse_errors'])))
    w('Rules (exact):\n')
    for k in ('family', 'constant_factor', 'max_arity_nonconstant', 'contains_zero', 'normalized_identity', 'dedup', 'salted_order', 'strata'):
        w('- **%s**: %s' % (k, ui['rules'][k]))
    w('\nFamilies in the archive (filename-prefix rule): %s.\n' % ', '.join('%s %d' % kv for kv in sorted(ui['families'].items())))
    w('### 2.1 Dedup (%d removed, %d flagged and kept)\n' % (len(ui['removed']), len(ui['flagged_same_model_different_evidence'])))
    for r in ui['removed']:
        w('- `%s`: %s' % (r['name'], '; '.join('%s %s' % (x['reason'], x['of']) for x in r['reasons'])))
    w('\nFlagged (model bytes identical to an earlier archive model, evidence different -> distinct MAR task, KEPT): %s.\n' % ', '.join('`%s`=`%s`' % (f['name'], f['flags'][0]['of']) for f in ui['flagged_same_model_different_evidence']))
    w('Normalized-identity dedup found no duplicate that the byte rule missed (every normalized-model group with >1 member is also byte-identical).\n')
    w('### 2.2 Strata and selection (target 16 = 8 strata x 2 size buckets)\n')
    w('| stratum | archive models | eligible after dedup | lower slot | upper slot |\n|---|---|---|---|---|')
    slots = {s['slot']: s for s in us['slots']}
    for st in STRATUM_ORDER:
        key = '|'.join(st); lo = slots[key + '|lower']; up = slots[key + '|upper']
        f = lambda s: ('**%s** (%s)' % (s['name'], s['family']) if s['status'] == 'SELECTED' else s['status'])
        w('| %s | %d | %d | %s | %s |' % (key, ui['archive_counts_per_stratum'][key], ui['eligible_counts_per_stratum'][key], f(lo), f(up)))
    w('\nSelected %d of 16; unavailable %d (%s). Family counts among selected: %s (cap 2 respected). The predeclared metadata-only round-robin permitted by the note was **not** applied; the deficit is left visible. Six of the eight strata are empty in the FINAL MAR archive itself or become empty after legacy dedup: the three archive models in `binary|arity>2|zero-free` (`%s`) are byte-identical to legacy inputs, and no archive model is binary with max nonconstant arity <= 2, or nonbinary with arity > 2.\n' % (
        us['selected'], us['unavailable'], ', '.join('%s %d' % kv for kv in us['unavailable_breakdown'].items() if kv[1]), us['family_counts_selected'],
        ', '.join(m['name'] for m in ui['models'] if m['stratum'] == 'binary|arity>2|zero-free')))
    w('Selected models (name, family, bytes, n, factors, evidence count, byte sha256):\n')
    for s in us['slots']:
        if s['status'] == 'SELECTED':
            w('- `%s` [%s] %s: %d B, n=%d, %d factors, evidence %d, `%s`' % (s['slot'], s['family'], s['name'], s['file_bytes'], s['n_vars'], s['n_factors'], s['evidence_count'], s['byte_sha256']))
    w('\nSelection detail per slot (median, candidate count, first candidates in salted order) is in `UAI2022_SELECTION.json`. Buckets with a single candidate (e.g. `nonbinary|arity<=2|zero-free|upper`) are filled by that candidate; the hash order has no effect there.\n')
    if mi and ms:
        fm = mi['format']
        w('## 3. MC 2024 Track 2 (nonnegative WMC)\n')
        w('Competition tar: %d instances `mc2024_track2-random_<000..199>.cnf.xz` + `shasums.txt` (sha1 of the UNCOMPRESSED `.cnf`; %d/%d verified). Extracted to `external/mc2024_track2_competition/`. Odd index = originally private final-evaluation instance (%d odd); the Zenodo record text confirms the even/odd convention.\n' % (mi['n_instances'], mi['n_organizer_sha1_matches'], mi['n_instances'], mi['n_odd']))
        w('### 3.1 Format findings (confirmed from the files, not assumed)\n')
        w('- Observed layout: `%s`.' % fm['observed'])
        w('- Weight lines per instance: %s; both literal weights given for all variables in every instance: %s.' % (fm['weight_lines_per_instance'], fm['both_literal_weights_all']))
        w('- The description page states "%s". Observed: %d instances carry unit pairs (1, 1) for some variables (%d variables in total) and %d instances have variables with NO weight line at all (%d variables; the converter uses 1, 1 and records them); %d variables carry a genuinely weighted pair.' % (fm['mc2024_description_page_statement'], fm['instances_with_unit_pairs'], fm['total_unit_pairs'], fm['instances_with_no_weight_line_vars'], fm['total_no_weight_line_vars'], fm['total_weighted_pairs']))
        w('- "Normalized" (every variable has both weight lines and each pair is either exactly w(x)+w(-x)==1 as decimals or the unit pair (1,1)): %d/%d instances; allowing variables with no weight line as "none" and comparing in float64: %d/%d. The remaining %d instances (%s) have weighted pairs whose decimal strings do not sum to 1 exactly (%d pairs do not even sum to 1 in float64, e.g. `0.00008547803498087751 + 0.9999145219650192`); these look like float-printed normalized weights and are kept as the exact rationals written in the file - the converter binds the literal weights as written, never re-normalized.' % (
            fm['normalized_exact_count'], mi['n_instances'], fm['normalized_or_none_float64_count'], mi['n_instances'], mi['n_instances'] - fm['normalized_or_none_float64_count'],
            ', '.join('`%s`' % r['name'] for r in mi['instances'] if r['vars_weighted_pair_not_normalized_float64']), fm['weighted_pairs_not_normalized_float64']))
        w('- Clauses with a repeated literal (merged by the converter): %d clauses in %d instances. Instances with an effective clause length > 3 (need OR-gate auxiliaries): %d/%d.' % (fm['clauses_with_repeated_literals'], fm['instances_with_repeated_literal_clauses'], fm['max_clause_length_over_3_instances'], mi['n_instances']))
        w('- Header `p cnf n m` matches the parsed clause count in all instances: %s.' % fm['header_matches_all'])
        w('- Refused (negative or non-rational weight): %s.' % (fm['refused'] or 'none - every weight in all 200 instances is a nonnegative decimal'))
        w('- %s' % fm['note'])
        ns = sorted(r['n_vars'] for r in mi['instances']); bs = sorted(r['cnf_bytes'] for r in mi['instances']); ks = sorted(r['max_clause_length_raw'] for r in mi['instances'])
        w('- n: min %d / median %d / max %d; uncompressed bytes: min %d / median %d / max %d; max clause length: min %d / median %d / max %d. No instance has n <= 12, so the full-enumeration conversion certificate applies to synthetic tests only (section 4).\n' % (ns[0], ns[len(ns) // 2], ns[-1], bs[0], bs[len(bs) // 2], bs[-1], ks[0], ks[len(ks) // 2], ks[-1]))
        w('### 3.2 Family mapping\n')
        w(mi['family_mapping']['statement'] + ' Method: %s. Mapped %d, unmapped %d. Mapped instances: %s.\n' % (mi['family_mapping']['method'], mi['family_mapping']['n_mapped'], mi['family_mapping']['n_unmapped'],
          ', '.join('`%s`->%s' % (r['name'], r['collected_match']) for r in mi['instances'] if r['family_mapped']) or 'none'))
        w('**Family-level claims are therefore not possible**; rows are instance-level. Prior exposure audit: %s.\n' % ms['prior_exposure_audit'])
        w('### 3.3 Selection (target 8)\n')
        w('Rule: %s\n' % ' '.join(ms['rule'].split()))
        w('Coverage deficit: %s\n' % ms['coverage_deficit'])
        w('| slot | instance | index | family row | bytes | n | m | max k | converted entries | within cap |\n|---|---|---|---|---|---|---|---|---|---|')
        for s in ms['slots']:
            if s['status'] == 'SELECTED':
                w('| %s | `%s` | %d (%s) | %s | %d | %d | %d | %d | %d | %s |' % (s['slot'], s['name'], s['index'], 'odd' if s['odd_index'] else 'EVEN', s['family'], s['cnf_bytes'], s['n_vars'], s['m_header'], s['max_clause_length'], s['converted_table_entries'], s['conversion_within_cap']))
            else:
                w('| %s | %s | | | | | | | | |' % (s['slot'], s['status']))
        w('\nSelected %d of 8; even-index fallback used: %s. Over the conversion cap (%d entries): %s.\n' % (ms['selected'], ms['even_fallback_used'], CONVERSION_CAP, ms['over_cap_selected'] or 'none'))
        w('**Selection bias caveat (from the note and the organizers):** %s\n' % ms['selection_bias_note'])
    if cv:
        w('## 4. WCNF -> UAI conversion (`cex/cqr/wcnf.py`)\n')
        w('Encoding: CNF variable i -> UAI variable i-1 (cardinality 2, state 1 = true); literal weights -> unary factor `[w(-x), w(x)]` (missing weight -> 1, recorded); clause of effective length k <= 3 -> one 0/1 factor over its variables; k > 3 -> k-2 auxiliary variables through deterministic OR gates of arity 3 (`y1 = l1 v l2`, `yj = y(j-1) v l(j+1)`, final factor `1[y(k-2) v lk]`). Every auxiliary is uniquely determined by the original assignment, so Z(UAI) = WMC(CNF) exactly. Written as `MARKOV`, with an empty `.evid` (`0`) and a `.conversion.json` sidecar (clause -> factor map, auxiliary count, original literal weights, scan metadata). Table size = 2n + sum over clauses (2^k if k <= 3 else 8(k-2)+4); cap %d entries.\n' % cv['cap_entries'])
        w('### 4.1 Synthetic unit tests and certificate (full enumeration, n <= 12)\n')
        for t in cv['synthetic_tests']:
            if 'certificate' in t:
                c = t['certificate']; w('- `%s`: WMC direct = %s, Z(UAI) brute force = %s, equal = %s, expected %s; %d auxiliaries, %d factors; pointwise unique-completion check on %d assignments -> %s' % (t['test'], c['wmc_direct'], c['uai_Z_bruteforce'], c['equal'], t['expected'], t['auxiliary_vars'], t['factors'], t['pointwise_assignments_checked'], t['status']))
            else:
                w('- `%s`: %s %s' % (t['test'], t['status'], ('(%d random weighted CNFs, n <= 8, clause length 1..6, each certified by full enumeration)' % t['cases']) if 'cases' in t else (t.get('detail') or '')[:100]))
        w('\n### 4.2 Converted selected instances\n')
        for r in cv['conversions']:
            if r['status'] == 'CONVERTED':
                w('- `%s`: CONVERTED -> `%s` (%d B, sha256 `%s`): %d original + %d auxiliary vars, %d factors, %d table entries; missing weights defaulted: %d; certificate: %s; pointwise check: %s' % (
                    r['name'], os.path.relpath(r['uai_path'], CODE), r['uai_bytes'], r['uai_sha256'], r['n_original_vars'], r['n_auxiliary_vars'], r['n_factors'], r['table_entries'], r['missing_weights_defaulted'],
                    r['certificate'].get('status', 'equal=%s' % r['certificate'].get('equal')), r['pointwise_check']['status'] + (' (%d assignments; %s)' % (r['pointwise_check']['assignments'], r['pointwise_check']['reader'].split(' (')[0]) if 'assignments' in r['pointwise_check'] else '')))
            else:
                w('- `%s`: %s (%s entries)' % (r['name'], r['status'], r.get('converted_table_entries')))
        w('\nThe pointwise check evaluates the factor product at a few original assignments (auxiliaries recomputed from the gate semantics) and verifies that every single auxiliary flip gives product 0; it is a representation check, not inference. Native CNF and converted UAI are two representations of one problem; the sidecar binds the original literal weights.\n')
    w('## 5. Refusals and unavailable rows\n')
    w('- UAI 2022: %d of 16 slots UNAVAILABLE_STRATUM_EMPTY (listed in section 2.2); no slot was filled from another stratum.' % us['unavailable'])
    if mi and ms:
        w('- MC 2024: parser refusals (REFUSED_NEGATIVE_OR_NONRATIONAL_WEIGHT): %s; the parser-refusal path is exercised by the synthetic controls `control_negative_weight` and `control_nonrational_weight`. Track 2b (negative weights) was not downloaded (excluded from the inference domain by the note). Converted representation unavailable (UNAVAILABLE_CONVERSION_CAP): %s.' % (mi['format']['refused'] or 'none in the 200 competition instances', ms['over_cap_selected'] or 'none'))
    w('- CIRCUIT_ARTIFACT_PENDING (probabilistic circuits) remains pending; nothing was acquired for it in this stage.\n')
    w('## 6. Time charged (scope `cqr_acquisition`)\n')
    w('| job | outcome | wall s |\n|---|---|---|')
    for r in receipts:
        w('| %s | %s | %.3f |' % (r['job'], r['outcome'], r.get('wall_s') or 0.0))
    w('| **total** | %d receipts | **%.3f** |\n' % (len(receipts), charged))
    if other_scopes:
        w('The ledger is shared: it also holds receipts of other scopes (%s) written by other stages; they are NOT part of this acquisition total.\n' % ', '.join('`%s` x%d' % kv for kv in sorted(other_scopes.items())))
    w('Wall seconds are the supervisor receipts\' `wall_s` (download transfers, archive parsing and conversion). The parse and conversion jobs include the time of the metadata scans themselves; nothing here is an inference timing. Interactive shell steps outside the supervisor (extraction with `unzip`/`tar`, writing these JSON files, the determinism test) are not charged in the ledger and are disclosed as such.\n')
    out = os.path.join(EXT, 'ACQUISITION_REPORT.md')
    with open(out, 'w') as f:
        f.write('\n'.join(L))
    print('wrote', os.path.relpath(out, CODE), os.path.getsize(out), 'bytes; charged %.3f s over %d receipts' % (charged, len(receipts)))


def cmd_all(a):
    cmd_downloads(a); cmd_uai_inventory(a); cmd_uai_select(a); cmd_mc_inventory(a); cmd_mc_select(a); cmd_convert(a); cmd_report(a)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd', choices=['downloads', 'uai-inventory', 'uai-select', 'mc-inventory', 'mc-select', 'convert', 'report', 'all'])
    a = ap.parse_args()
    {'downloads': cmd_downloads, 'uai-inventory': cmd_uai_inventory, 'uai-select': cmd_uai_select, 'mc-inventory': cmd_mc_inventory, 'mc-select': cmd_mc_select, 'convert': cmd_convert, 'report': cmd_report, 'all': cmd_all}[a.cmd](a)
