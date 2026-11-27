"""Compatibility entry: ``python -m pgm.build`` builds the host-native kernels (``pgm.runtime.build``)."""
from .runtime.build import main

if __name__ == "__main__":
    main()
