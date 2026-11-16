import time
from collections.abc import Generator
from contextlib import contextmanager


@contextmanager
def measure_time(name: str) -> Generator[None]:
    """Context manager for measuring execution performance."""
    start = time.perf_counter()
    yield
    end = time.perf_counter()
    print(f"[{name}] took {end - start:.5f} seconds")
