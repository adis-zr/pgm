"""Build host-native kernels before timing inference calls (explicit setup; never part of a timed request)."""
import json


def main():
    from ..backends import structural, response
    results = {}
    cx, sf = structural.native_modules()
    hn = response.native_module()
    for name, module in [("contraction", cx), ("bipartite_stream", sf), ("heatbath", hn)]:
        built = module.build()
        results[name] = built[1] if isinstance(built, tuple) else built
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
