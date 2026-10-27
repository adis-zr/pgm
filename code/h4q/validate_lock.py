"""Automatic validation of the design lock's internal bindings (addendum §5: the stale DESIGN.md and
DESIGN_PROGRESS.md hashes must be regenerated and validated automatically, not by hand)."""
import sys, os, json, hashlib, glob
D = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                 "docs", "h4-complete-query-pilot-design-2026-10-27")
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
L = json.load(open(os.path.join(D, "DESIGN_LOCK.json")))
bad = []
for group in ("design_documents", "review_notes", "frozen_inputs", "proof_documents"):
    for f, h in L["identities"].get(group, {}).items():
        p = f if os.path.isabs(f) else os.path.join(D, f)
        if group in ("frozen_inputs",): p = os.path.join(D, "..", "h4-arithmetic-contract-2026-10-27", "inputs", f)
        if group in ("proof_documents",): p = os.path.join(D, "..", "h4-arithmetic-contract-2026-10-27", f)
        if not os.path.exists(p): bad.append((group, f, "missing")); continue
        if sha(p) != h: bad.append((group, f, "hash mismatch"))
print(json.dumps({"lock_bindings_valid": not bad, "mismatches": bad}, indent=1))
sys.exit(0 if not bad else 1)
