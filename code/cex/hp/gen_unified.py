"""Fresh structural scale panel of the unified-planner pilot (brief section 9): topology {cycle16, grid4x4} x cardinality {32} x family {exact, perturbed, generic} with the UNCHANGED
hp_gen generation / permutation algorithms (build + permute imported, not modified) under the seed tag UNIFIED-REPRESENTATION-PLANNER-PILOT-1 (same SHA-256-to-seed convention, Python PRNG,
independent '|perm' substream; perturbation 1/16384, coarse tables 1..9, unary 1..9/8, scales 2^k with k in -3..3, generic entries 1..31/16). usage: gen_unified.py OUTDIR"""
import sys, os, json, hashlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import hp_gen as G
TAG = 'UNIFIED-REPRESENTATION-PLANNER-PILOT-1'; CARD = 32

def generate(outdir, tag=TAG):
    os.makedirs(outdir, exist_ok=True); man = []
    for topo in G.TOPOLOGIES:
        for fam in G.FAMILIES:
            m0, rec = G.build(tag, topo, CARD, fam); m, pi = G.permute(tag, topo, CARD, fam, m0); name = '%s_c%d_%s' % (topo, CARD, fam); p = os.path.join(outdir, name + '.uai'); G.write(p, m)
            json.dump(dict(name=name, tag=tag, seed=G.seed_of(tag, topo, CARD, fam), perm_seed=G.seed_of(tag, topo, CARD, fam, '|perm'), generative_record=rec, permutation=pi), open(os.path.join(outdir, name + '.generative_map.json'), 'w'), indent=1, default=str)
            man.append(dict(name=name, topology=topo, card=CARD, family=fam, nvars=16, nfactors=len(m['factors']), entries=sum(len(f['values']) for f in m['factors']), K=16 * CARD, model=os.path.abspath(p), evidence_file=os.path.abspath(p + '.evid'), model_sha256=hashlib.sha256(open(p, 'rb').read()).hexdigest(), evid_sha256=hashlib.sha256(open(p + '.evid', 'rb').read()).hexdigest()))
    json.dump(dict(tag=tag, generator_sha256=hashlib.sha256(open(__file__, 'rb').read()).hexdigest(), hp_gen_sha256=hashlib.sha256(open(os.path.join(HERE, 'hp_gen.py'), 'rb').read()).hexdigest(), inputs=man), open(os.path.join(outdir, 'GENERATED_MANIFEST.json'), 'w'), indent=1)
    return man

if __name__ == '__main__':
    for m in generate(sys.argv[1]): print(m['name'], m['nfactors'], 'factors', m['entries'], 'entries', 'K', m['K'], m['model_sha256'][:12])
