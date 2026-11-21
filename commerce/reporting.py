"""Read-only owner summaries from completed counter transactions."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import Product, Sale, SaleItem


ZERO = Decimal("0.00")


def commerce_dashboard_summary(*, today=None):
    """Use saved amounts and exclude drafts/cancellations from every total.

    Dates refer to sale creation because Sale has no completion timestamp.
    Shop/bar classification follows the current Product category; monetary
    snapshots never use the current Product price.
    """
    today = timezone.localdate() if today is None else today
    tz = timezone.get_current_timezone()
    first_date = today - timedelta(days=6)
    first_start = timezone.make_aware(datetime.combine(first_date, time.min), tz)
    tomorrow_start = timezone.make_aware(
        datetime.combine(today + timedelta(days=1), time.min), tz,
    )
    completed = Sale.objects.filter(status=Sale.Status.COMPLETED)
    sale_totals = completed.aggregate(total=Sum("total"), count=Count("pk"))
    items = SaleItem.objects.filter(sale__status=Sale.Status.COMPLETED)
    category_totals = items.aggregate(
        shop_total=Sum("line_total", filter=Q(product__category=Product.Category.SHOP)),
        bar_total=Sum("line_total", filter=Q(product__category=Product.Category.BAR)),
        shop_count=Count("sale_id", distinct=True, filter=Q(product__category=Product.Category.SHOP)),
        bar_count=Count("sale_id", distinct=True, filter=Q(product__category=Product.Category.BAR)),
    )
    daily_rows = completed.filter(
        created_at__gte=first_start, created_at__lt=tomorrow_start,
    ).annotate(day=TruncDate("created_at", tzinfo=tz)).values("day").annotate(
        total=Sum("total"), count=Count("pk"),
    ).order_by("day")
    by_day = {row["day"]: row for row in daily_rows}
    trend = []
    for offset in range(7):
        day = first_date + timedelta(days=offset)
        row = by_day.get(day, {})
        trend.append({"date": day, "total": row.get("total", ZERO), "count": row.get("count", 0)})
    alerts = Product.objects.filter(
        is_active=True, stock_quantity__lte=F("low_stock_threshold"),
    ).order_by("stock_quantity", "category", "name", "pk")
    return {
        "completed_sales_total": sale_totals["total"] or ZERO,
        "completed_sales_count": sale_totals["count"],
        "shop_sales_total": category_totals["shop_total"] or ZERO,
        "bar_sales_total": category_totals["bar_total"] or ZERO,
        "shop_sales_count": category_totals["shop_count"],
        "bar_sales_count": category_totals["bar_count"],
        "sales_created_today_total": trend[-1]["total"],
        "sales_created_today_count": trend[-1]["count"],
        "sales_creation_trend": trend,
        "inventory_alert_count": alerts.count(),
        "inventory_alerts": alerts[:8],
        "recent_completed_sales": completed.select_related("member").order_by("-created_at", "-pk")[:6],
    }
