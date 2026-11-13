"""Independent exact-oracle checks of the native binary64 stream.

Checks interval containment, not numerical point agreement. Range refusal is
allowed only on the separately labeled extreme-range controls.
"""
from pathlib import Path
from fractions import Fraction as F
import ctypes
import hashlib
import json
import random
import time
import traceback
import stream_float
import stream
from qualification import oracle, random_factors, permute, check_output, fingerprint


def hashes():
    base = Path(__file__).parent
    return {name: hashlib.sha256((base/name).read_bytes()).hexdigest()
            for name in ['stream_float.py', 'stream_kernel.cpp', 'libstream_kernel.so']}


def extreme(seed):
    rng = random.Random(seed)
    n = rng.randrange(2, 7)
    factors = []
    for v in range(n):
        vals = [F(10) ** rng.randrange(-200, 201) for _ in range(2)]
        factors.append({'scope': (v,), 'values': vals})
    for v in range(1, n):
        factors.append({'scope': (0, v),
                        'values': [F(10) ** rng.randrange(-200, 201) for _ in range(4)]})
    return permute({'cards': [2]*n, 'factors': factors, 'evidence': {}}, rng)


def run():
    provenance = stream_float.build()
    identity_before = hashes()
    rows = []
    coordinates = 0
    for kind, seed, model in [('ordinary', 31000+s, random_factors(31000+s, True, True)) for s in range(100)] + [
            ('extreme_range', 32000+s, extreme(32000+s)) for s in range(30)]:
        row = {'kind': kind, 'seed': seed, 'model_sha256': fingerprint(model)}
        start = time.monotonic()
        try:
            truth = oracle(model)
            try:
                result = stream_float.solve(model, deadline=time.monotonic()+5)
            except stream_float.RangeError as error:
                assert kind == 'extreme_range', str(error)
                row['outcome'] = 'SAFE_RANGE_REFUSAL'
                row['reason'] = str(error)
            else:
                count = check_output(model, result, truth)
                coordinates += count
                row['outcome'] = 'ENCLOSED'
                row['coordinates_checked'] = count
                row['max_width'] = str(max((hi-lo for rr in result['intervals'] for lo,hi in rr), default=F(0)))
            row['status'] = 'PASS'
        except Exception as error:
            row['status'] = 'FAIL'
            row['error'] = repr(error)
            row['traceback'] = traceback.format_exc()
        row['seconds'] = time.monotonic()-start
        rows.append(row)
    guards = []
    for name, model in [('expired_empty', {'cards': [], 'factors': [], 'evidence': {}}),
                        ('expired_observed', {'cards':[2], 'factors':[{'scope':(0,), 'values':[F(1),F(1)]}], 'evidence':{0:1}})]:
        row = {'name':name}
        try:
            try:
                stream_float.solve(model, deadline=time.monotonic()-1)
            except TimeoutError:
                pass
            else:
                raise AssertionError('expired native wrapper returned success')
            row['status']='PASS'
        except Exception as error:
            row['status']='FAIL';row['error']=repr(error)
        guards.append(row)
    libc=ctypes.CDLL(None)
    old=libc.fegetround()
    row={'name':'changed_rounding_environment'}
    try:
        import platform;FE_UPWARD=0x400000 if platform.machine() in ('arm64','aarch64') else 0x800   # HOST ADAPTER: FE_UPWARD is ABI-specific (x86: 0x800; arm64: 0x400000)
        assert libc.fesetround(FE_UPWARD)==0
        try:
            stream_float.solve({'cards':[2,2], 'evidence':{},
                                'factors':[{'scope':(0,1),'values':[F(1)]*4}]},
                               deadline=time.monotonic()+5)
        except stream_float.RangeError as error:
            assert 'environment' in str(error)
        else:
            raise AssertionError('non-nearest floating environment accepted')
        row['status']='PASS'
    except Exception as error:
        row['status']='FAIL';row['error']=repr(error)
    finally:
        assert libc.fesetround(old)==0
    guards.append(row)
    after=hashes()
    assert identity_before==after, 'implementation changed during qualification'
    return {'build':provenance, 'qualified_hashes':after, 'records':rows,
            'guards':guards, 'models':len(rows),
            'ordinary_enclosures':sum(x.get('outcome')=='ENCLOSED' and x['kind']=='ordinary' for x in rows),
            'extreme_enclosures':sum(x.get('outcome')=='ENCLOSED' and x['kind']=='extreme_range' for x in rows),
            'safe_range_refusals':sum(x.get('outcome')=='SAFE_RANGE_REFUSAL' for x in rows),
            'coordinates_checked':coordinates,
            'all_pass':all(x['status']=='PASS' for x in rows+guards),
            'scope':'Small-model exact-oracle numerical qualification of this precise build; not independent replay of benchmark outputs.'}


if __name__=='__main__':
    out=run()
    Path(__file__).with_name('native_qualification.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k not in ('records','build','qualified_hashes')},indent=2))
    for row in out['records']:
        if row['status']!='PASS': print(row)
