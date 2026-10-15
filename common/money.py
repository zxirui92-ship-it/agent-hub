"""CNY yuan at public boundaries; decimal arithmetic, at most two places.

Legacy source archives retain integer cents for byte-for-byte provenance.
Only their explicit reader uses cents_to_yuan; API inputs are never guessed.
"""
from decimal import Decimal, ROUND_HALF_UP

MAX_YUAN = Decimal('999999999999.99')


def is_yuan(value) -> bool:
    if type(value) not in (int, float):
        return False
    amount = Decimal(str(value))
    return (amount.is_finite() and abs(amount) <= MAX_YUAN
            and amount * 100 == (amount * 100).to_integral_value())


def yuan_schema(minimum=0):
    return {'type': 'number', 'format': 'cny-yuan', 'minimum': minimum,
            'maximum': float(MAX_YUAN), 'description': '人民币元，最多两位小数'}


def format_yuan(amount) -> str:
    if not is_yuan(amount):
        raise ValueError('金额必须为有限数值（元），最多两位小数，绝对值不超过 999999999999.99')
    return f'{Decimal(str(amount)):.2f}'


def cents_to_yuan(amount: int) -> float:
    if type(amount) is not int or amount < 0:
        raise ValueError('归档源金额必须为非负整数分')
    value = Decimal(amount) / 100
    if value > MAX_YUAN:
        raise ValueError('归档源金额超过支持范围')
    return float(value)


def average_yuan(amount, count: int) -> float:
    format_yuan(amount)
    return float((Decimal(str(amount)) / count).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def format_cents(amount: int) -> str:
    """Format archived cents for diagnostics only; public amounts use format_yuan."""
    if type(amount) is not int:
        raise TypeError('amount must be integer cents')
    whole, cents = divmod(abs(amount), 100)
    return f'{"-" if amount < 0 else ""}{whole}.{cents:02d}'
