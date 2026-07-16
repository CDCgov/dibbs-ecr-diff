import time
from contextlib import contextmanager
from types import GeneratorType


@contextmanager
def measure_time(name: str) -> GeneratorType[None]:
    """Context manager for measuring execution performance."""
    start = time.perf_counter()
    yield
    end = time.perf_counter()
    print(f"[{name}] took {end - start:.5f} seconds")
