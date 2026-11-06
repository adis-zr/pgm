// libDAI MAR driver for the external sweep: reads a UAI model + UAI evidence, clamps the evidence (surgery: the clamped variable is
// removed from every factor by slicing, the libDAI way), runs ONE named algorithm with a FROZEN property string, writes the marginal of
// every ORIGINAL variable in ORIGINAL variable order and ORIGINAL state order (observed variables as point masses) in UAI MAR format:
//   MAR\n<nvars> <k_0> p.. <k_1> p.. ...\n
// plus a JSON side record with phase timings. It also prints BP convergence information. No algorithm choice is made here: the
// algorithm and its properties are command-line arguments frozen in the campaign manifest.
//   libdai_mar MODEL.uai EVID.uai.evid OUT.MAR SIDE.json "BP[inference=SUMPROD,updates=SEQMAX,logdomain=0,tol=1e-9,maxiter=10000,damping=0.0,maxtime=18]"
#include <dai/alldai.h>
#include <dai/io.h>
#include <dai/jtree.h>
#include <dai/bp.h>
#include <iostream>
#include <fstream>
#include <iomanip>
#include <chrono>
#include <set>
using namespace dai; using namespace std;
static double now() { return chrono::duration<double>(chrono::steady_clock::now().time_since_epoch()).count(); }
int main(int argc, char* argv[]) {
    if (argc != 6) { cerr << "usage: libdai_mar MODEL.uai EVID.uai.evid OUT.MAR SIDE.json ALG[props]" << endl; return 2; }
    double t0 = now();
    vector<Var> vars; vector<Factor> facs; vector<Permute> perms;
    ReadUaiAieFactorGraphFile(argv[1], 0, vars, facs, perms);
    // evidence: the UAI 2014 single-assignment format "<n> <var> <val> ..." (whitespace-delimited, any line breaks); parsed here because
    // libDAI's reader expects the 2010 multi-case layout (a case-count header line)
    map<size_t,size_t> ev;
    { ifstream ef(argv[2]); size_t n = 0; if (!(ef >> n)) n = 0; for (size_t i = 0; i < n; ++i) { size_t v, s; if (!(ef >> v >> s)) { cerr << "truncated evidence" << endl; return 3; } if (v >= vars.size() || s >= vars[v].states()) { cerr << "evidence out of range" << endl; return 3; } if (ev.count(v)) { cerr << "duplicate evidence variable" << endl; return 3; } ev[v] = s; }
      string extra; if (ef >> extra) { cerr << "trailing evidence tokens" << endl; return 3; } }
    double t_parse = now();
    FactorGraph fg(facs);
    // clamp evidence by surgery: for each observed variable, slice every factor containing it, then drop the variable
    vector<Factor> clamped;
    for (size_t I = 0; I < fg.nrFactors(); ++I) {
        Factor f = fg.factor(I);
        for (map<size_t,size_t>::const_iterator it = ev.begin(); it != ev.end(); ++it) {
            Var v = vars[it->first];
            if (f.vars().contains(v)) f = f.slice(VarSet(v), it->second);   // partial evaluation at the observed state
        }
        if (f.vars().size() > 0) clamped.push_back(f);
    }
    // variables that appear in no remaining factor (isolated after clamping) need a uniform factor so their marginal is defined
    { std::set<size_t> present; for (size_t I = 0; I < clamped.size(); ++I) for (VarSet::const_iterator v = clamped[I].vars().begin(); v != clamped[I].vars().end(); ++v) present.insert(v->label());
      for (size_t i = 0; i < vars.size(); ++i) if (ev.count(i) == 0 && !present.count(vars[i].label())) clamped.push_back(Factor(vars[i])); }
    FactorGraph fgc(clamped);
    double t_build = now();
    string algspec(argv[5]);
    InfAlg* ia = newInfAlgFromString(algspec, fgc);
    double t_construct = now();
    ia->init();
    double converged_at = -1; size_t iters = 0; Real maxdiff = -1;
    ia->run();
    iters = ia->Iterations(); maxdiff = ia->maxDiff();
    double t_run = now();
    // write MAR in ORIGINAL variable / state order
    ofstream out(argv[3]);
    out << "MAR" << endl << vars.size();
    out << setprecision(10);
    for (size_t i = 0; i < vars.size(); ++i) {
        size_t k = vars[i].states();
        out << " " << k;
        if (ev.count(i)) { for (size_t s = 0; s < k; ++s) out << " " << (s == ev[i] ? 1.0 : 0.0); }
        else { Factor b = ia->belief(vars[i]); for (size_t s = 0; s < k; ++s) out << " " << (double)b[s]; }
    }
    out << endl; out.close();
    double t_out = now();
    ofstream side(argv[4]);
    side << "{\"algorithm\": \"" << algspec << "\", \"iterations\": " << iters << ", \"maxdiff\": " << maxdiff
         << ", \"converged\": " << ((maxdiff >= 0 && maxdiff <= 1e-9) ? "true" : "false")
         << ", \"logZ\": " << ia->logZ() << ", \"n_vars\": " << vars.size() << ", \"n_evidence\": " << ev.size() << ", \"n_factors_after_clamp\": " << fgc.nrFactors()
         << ", \"phases_s\": {\"parse\": " << (t_parse - t0) << ", \"clamp_build\": " << (t_build - t_parse) << ", \"construct\": " << (t_construct - t_build)
         << ", \"run\": " << (t_run - t_construct) << ", \"serialize\": " << (t_out - t_run) << ", \"total\": " << (t_out - t0) << "}}" << endl;
    delete ia;
    return 0;
}
