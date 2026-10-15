"""JSON decoding for data boundaries that must not admit non-finite numbers."""
import json
import math
from typing import Any


def _reject_constant(value: str) -> None:
    raise ValueError(f'Non-standard JSON numeric constant: {value}')


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('JSON number exceeds the finite float range')
    return result


def strict_json_loads(value: str | bytes | bytearray) -> Any:
    """Decode JSON, rejecting NaN/Infinity and floating-point overflow.

    Integers retain Python's exact integer representation; strings containing
    words such as "NaN" remain ordinary strings.
    """
    return json.loads(value, parse_constant=_reject_constant, parse_float=_finite_float)
