"""Numbers the Gold publish has to reproduce.

They come from the Session 3 sales fact plus the Session 4 change feed.
A second build has to land on the same figures. The clock is not an input.
"""

from __future__ import annotations

from decimal import Decimal

GROSS_SALES = Decimal("3779.50")
RETURN_AMOUNT = Decimal("12.50")
NET_SALES = Decimal("3767.00")
AVERAGE_ORDER_GROSS = Decimal("377.95")
SUSPENSE_AMOUNT = Decimal("749.00")
WEEKEND_GROSS = Decimal("889.00")

FACT_ROWS = 11
ORDER_COUNT = 10
UNITS_SOLD = 18
UNITS_RETURNED = 1
CUSTOMER_REGISTRY_ROWS = 10
PRODUCT_REGISTRY_ROWS = 11
DATE_ROWS = 31

SMARTPHONES = Decimal("3426.00")
ACCESSORIES_AS_WAS = Decimal("211.00")
ACCESSORIES_AS_IS = Decimal("97.00")
POWER_AS_IS = Decimal("114.00")
HOME_APPLIANCES = Decimal("89.00")
PERSONAL_CARE = Decimal("53.50")

CONSUMER_PHONES_AS_WAS = Decimal("1948.00")
BUSINESS_PHONES_AS_WAS = Decimal("1478.00")
CONSUMER_PHONES_AS_IS = Decimal("749.00")
BUSINESS_PHONES_AS_IS = Decimal("2677.00")
C101_PHONE = Decimal("1199.00")

C100_KEY = 1
C101_VERSION_1_KEY = 2
C101_VERSION_2_KEY = 9
C050_KEY = 10
P104_VERSION_1_KEY = 4
P104_VERSION_2_KEY = 11
UNKNOWN_KEY = -1
