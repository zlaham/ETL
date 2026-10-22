"""Governed changes that arrive after the Session 3 Silver publish.

These rows are not in Session 3 Bronze. They are the next business events Gold
has to absorb without rewriting the sales that already happened.
"""

from __future__ import annotations

CUSTOMER_CHANGES = (
    {
        "customer_id": "C100",
        "change_type": "type1",
        "attribute": "customer_name",
        "new_value": "John A. Smith",
        "effective_from": "2026-10-18",
        "reason": "legal_name_correction",
    },
    {
        "customer_id": "C101",
        "change_type": "type2",
        "attribute": "customer_segment",
        "new_value": "Business",
        "effective_from": "2026-10-17",
        "reason": "account_upgraded",
    },
)

NEW_CUSTOMERS = (
    {
        "customer_id": "C050",
        "customer_name": "Samir Haddad",
        "country_code": "LB",
        "customer_segment": "Business",
        "effective_from": "2026-10-18",
        "reason": "new_account",
    },
)

PRODUCT_CHANGES = (
    {
        "product_id": "P104",
        "change_type": "type2",
        "attribute": "category",
        "new_value": "Power",
        "effective_from": "2026-10-18",
        "reason": "merchandising_reclass",
    },
)

RETURN_EVENTS = (
    {
        "return_id": "R-1005-1",
        "order_line_id": "OL-1005-1",
        "quantity": 1,
        "return_amount": "12.50",
        "return_date": "2026-10-19",
        "reason": "customer_return",
    },
)

LATE_SALES = (
    {
        "order_line_id": "OL-1026-1",
        "order_id": "ORD-1026",
        "customer_id": "C109",
        "product_id": "P101",
        "quantity": 1,
        "unit_price": "749.00",
        "order_date": "2026-10-18",
    },
)
