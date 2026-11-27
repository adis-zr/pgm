"""Build host-native kernels before timing inference calls."""
import json
from .backends.worker import _install_paths

def main():
    _install_paths()
    import cex_executor, stream_float, heatbath_native
    results={}
    for name,module in [("contraction",cex_executor),("bipartite_stream",stream_float),("heatbath",heatbath_native)]:
        built = module.build()
        results[name] = built[1] if isinstance(built, tuple) else built
    print(json.dumps(results,indent=2,default=str))

if __name__ == "__main__":main()
