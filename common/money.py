"""Exact display of integer-cent amounts, without a float round trip."""


def format_cents(amount: int) -> str:
    if type(amount) is not int:
        raise TypeError('amount must be integer cents')
    whole, cents = divmod(abs(amount), 100)
    return f'{"-" if amount < 0 else ""}{whole}.{cents:02d}'
