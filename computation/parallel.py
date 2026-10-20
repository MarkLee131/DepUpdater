"""Bound queued work while retaining input order and propagating failures."""
from collections import deque
from itertools import islice


def bounded_map(executor, function, items, limit):
    if limit < 1:
        raise ValueError('Pending task limit must be positive')
    items = iter(items)
    pending = deque()
    try:
        for item in islice(items, limit):
            pending.append(executor.submit(function, item))
        while pending:
            result = pending.popleft().result()
            for item in islice(items, 1):
                pending.append(executor.submit(function, item))
            yield result
    finally:
        for future in pending:
            future.cancel()
