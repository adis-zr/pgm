"""Compatibility entry: ``python -m pgm.supervision`` is the owned-tree supervisor (``pgm.runtime.supervision``)."""
from .runtime.supervision import implementation, main

if __name__ == "__main__":
    main()
