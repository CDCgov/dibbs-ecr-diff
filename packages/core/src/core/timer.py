from time import perf_counter


class timer:
    def __init__(self, name=""):
        self.name = name

    def __enter__(self):
        self.t0 = perf_counter()

    def __exit__(self, *args):
        print(f"{self.name}: {perf_counter() - self.t0:.6f}s")


# # usage
# with timer("block"):
#     ...
