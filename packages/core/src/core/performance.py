import time
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def measure_time(name: str) -> Iterator[None]:
    """Context manager for measuring execution performance."""
    start = time.perf_counter()
    yield
    end = time.perf_counter()
    print(f"[{name}] took {end - start:.5f} seconds")
