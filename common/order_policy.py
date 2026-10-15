"""Accepted source values and refund eligibility for the simulation project."""

REFUNDABLE_ORDER_STATUS = frozenset({'paid', 'shipped', 'delivered', 'completed'})
NON_REFUNDABLE_ORDER_STATUS = frozenset({'canceled', 'refunded', 'not_found', 'pending_payment', 'refunding'})
ORDER_STATUSES = (REFUNDABLE_ORDER_STATUS | NON_REFUNDABLE_ORDER_STATUS) - {'not_found'}
# watch is an observation flag in group02; only high_risk mandates manual review.
RISK_LEVELS = frozenset({'normal', 'watch', 'high_risk'})
