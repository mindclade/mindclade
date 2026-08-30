from collections.abc import Iterable, Iterator


class SequenceRandom:
    def __init__(self, values: Iterable[float]) -> None:
        self._values: Iterator[float] = iter(values)

    def unit(self) -> float:
        return next(self._values)
