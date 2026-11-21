"""
Commerce Views (Backend owned by Utkarsh, Frontend styled by Pratik)
"""

from django.shortcuts import render


def shop_index(request):
    """
    Placeholder view for Club Shop & Bar point-of-sale catalog.
    Handoff to Pratik:
    - Route name: 'commerce:shop'
    - Template path: 'commerce/index.html'
    - Context keys: 'page_title', 'products'
    """
    context = {
        'page_title': 'Shop & Bar',
        'products': [],  # To be populated by Utkarsh once Product model is migrated
    }
    return render(request, 'commerce/index.html', context)
