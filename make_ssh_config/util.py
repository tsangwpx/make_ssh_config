from __future__ import annotations

from typing import TypeVar, MutableMapping, Tuple

T = TypeVar('T')


def _missing():
    raise AssertionError


class CIDict(MutableMapping[str, T]):
    """
    Case-insensitive dict
    """

    def __init__(self, __m=None, **kwargs):
        self._data = {}

        if isinstance(__m, CIDict):
            self._data.update(__m._data)
        elif __m:
            self.update(__m)

        if kwargs:
            self.update(kwargs)

    def __setitem__(self, key: str, value: T):
        self._data[key.casefold()] = (key, value)

    def __getitem__(self, key: str):
        return self._data[key.casefold()][1]

    def __delitem__(self, key: str):
        del self._data[key.casefold()]

    def __iter__(self):
        for k, _ in self._data.values():
            yield k

    def __len__(self):
        return len(self._data)

    def clear(self):
        self._data.clear()

    def pop(self, key: str, default=_missing) -> T:
        pair = self._data.pop(key, None)
        if pair is None:
            if default is _missing:
                raise KeyError(key)
            return default
        return pair[1]

    def popitem(self) -> Tuple[str, T]:
        return self._data.popitem()[1]

    def setdefault(self, key: str, default: T = None) -> T:
        folded = key.casefold()
        _, v = self._data.setdefault(folded, (key, default))
        return v

    def __eq__(self, other):
        if isinstance(other, CIDict):
            this = {s: t for s, (_, t) in self._data.items()}
            that = {s: t for s, (_, t) in other._data.items()}
            return this == that
        else:
            return super().__eq__(other)

    def __repr__(self):
        return repr(dict(self))

    def __str__(self):
        return str(dict(self))


def dict_unpack(mapping, *keys):
    return [mapping[k] for k in keys]


def dict_gets(mapping, *keys, default=None):
    return [mapping.get(k, default) for k in keys]
