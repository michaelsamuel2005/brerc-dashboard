"""BRERC transactional notification delivery worker.

The package deliberately sits outside :mod:`etl`.  It can consume only the
small, fixed records returned by the notification-delivery database functions;
it never reads BRERC source rows or publication tables.
"""

from .models import ClaimedNotification, DeliveryFailure, DeliveryResult

__all__ = ["ClaimedNotification", "DeliveryFailure", "DeliveryResult"]
