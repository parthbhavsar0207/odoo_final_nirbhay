"""
Commerce App Models (Owned by Utkarsh)

Models to be implemented by Utkarsh:
- Product: name, category ('shop', 'bar'), price, stock quantity, low_stock_threshold, active
- Sale: member FK (references club.Member, nullable for guest/counter walk-ins), status, payment_method, subtotal, discount, total
- SaleItem: sale FK, product FK, quantity, unit_price snapshot, discount, line_total
- Enquiry (stretch): visitor contact, message, status, optional member link

CRITICAL INTEGRATION RULES:
1. Always reference Nayan's `club.Member` model via ForeignKey. Never create a separate customer/member table.
2. Migrations that add the foreign key to `club.Member` must explicitly declare a dependency on Nayan's core club migration.
3. Decrement stock atomically within transaction.atomic() upon sale completion; idempotent; restock on cancellation without double-restocking.
"""

from django.db import models

# Utkarsh will implement Product first (independent), and Sale/SaleItem once Nayan's Member migration lands.
