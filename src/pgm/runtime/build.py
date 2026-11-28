"""Build host-native kernels before timing inference calls (explicit setup; never part of a timed request)."""
import json
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h4", action="store_true", help="also build the optional H4 arithmetic producer/checker kernels (requires GMP/MPFR development libraries)")
    args = parser.parse_args(argv)
    from ..backends import structural, response
    results = {}
    cx, sf = structural.native_modules()
    hn = response.native_module()
    for name, module in [("contraction", cx), ("bipartite_stream", sf), ("heatbath", hn)]:
        built = module.build()
        results[name] = built[1] if isinstance(built, tuple) else built
    if args.h4:
        from ..algorithms.h4.kernels import build_all
        results["h4"] = build_all()
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
