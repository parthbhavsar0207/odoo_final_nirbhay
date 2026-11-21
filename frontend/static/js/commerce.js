/* Product selection only. All prices, discounts and inventory stay in Django. */
document.addEventListener('click', (event) => {
    const link = event.target.closest('[data-sell-product]');
    const form = document.getElementById('guest-sale-form');
    if (!link || !form) return;
    const product = form.elements.namedItem('product');
    const quantity = form.elements.namedItem('quantity');
    if (!product || !quantity) return;
    event.preventDefault();
    product.value = link.dataset.sellProduct;
    if (!quantity.value) quantity.value = '1';
    form.scrollIntoView({ behavior: 'smooth', block: 'center' });
    quantity.focus({ preventScroll: true });
});
