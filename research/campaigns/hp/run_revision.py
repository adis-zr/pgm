"""Historical protocol entry point retained as an explicit refusal on the live layout.

The historical calibration ablation requires the pinned 6c5690a reference layout and its original invocation.
The original source is preserved byte-for-byte in research/archive/historical_campaign_tools.
Use the packet's own pinned checkout and frozen harness to replay or validate that round.
The current external benchmark has its own independent runner and validator.
"""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_known_args()
    parser.exit(2, "HISTORICAL_PROTOCOL_ONLY: The historical calibration ablation requires the pinned 6c5690a reference layout and its original invocation. "
                "Restore the code and harness commits named by the packet's FREEZE.json / amendments; "
                "do not treat missing legacy paths as a successful comparison. "
                "No result, validation record, or scored archive was modified.\n")


if __name__ == "__main__":
    main()
