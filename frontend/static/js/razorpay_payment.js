/* Hosted Razorpay Test Mode UI; the server verifies payments and owns amounts. */
(() => {
    'use strict';

    const configElement = document.getElementById('razorpay-checkout-config');
    const payButton = document.getElementById('razorpay-pay-button');
    const verificationForm = document.getElementById('razorpay-verification-form');
    const feedback = document.getElementById('razorpay-feedback');
    if (!configElement || !payButton || !verificationForm || !feedback) return;

    let configuration;
    let submitting = false;
    let checkoutOpen = false;

    function showFeedback(message, isError = false) {
        feedback.textContent = message;
        feedback.hidden = false;
        feedback.dataset.error = String(isError);
        feedback.setAttribute('role', isError ? 'alert' : 'status');
    }

    function releaseCheckout() {
        checkoutOpen = false;
        if (!submitting) payButton.disabled = false;
    }

    try {
        configuration = JSON.parse(configElement.textContent);
    } catch (_) {
        payButton.disabled = true;
        showFeedback('Checkout configuration is unavailable. Reload this page before trying again.', true);
        return;
    }

    payButton.addEventListener('click', () => {
        if (submitting || checkoutOpen) return;
        if (typeof window.Razorpay !== 'function') {
            showFeedback('Razorpay checkout could not load. Check your connection and reload this page. No payment was submitted.', true);
            return;
        }
        if (!configuration.key || !configuration.key.startsWith('rzp_test_') || !configuration.order_id) {
            showFeedback('Razorpay Test Mode is not configured. No payment was submitted.', true);
            return;
        }

        payButton.disabled = true;
        checkoutOpen = true;
        feedback.hidden = true;
        try {
            const checkout = new window.Razorpay({
                key: configuration.key,
                order_id: configuration.order_id,
                amount: configuration.amount,
                currency: configuration.currency,
                name: configuration.name,
                description: configuration.description,
                method: {
                    card: configuration.method === 'card',
                    upi: configuration.method === 'upi',
                    netbanking: false, wallet: false, paylater: false, emi: false,
                },
                theme: { color: '#2563eb' },
                modal: {
                    ondismiss: () => {
                        if (!submitting) {
                            releaseCheckout();
                            showFeedback('Test checkout closed. No payment was verified; you can retry.');
                        }
                    },
                },
                handler: (response) => {
                    if (submitting) return;
                    const fields = ['razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature'];
                    if (!response || fields.some(name => typeof response[name] !== 'string' || !response[name])) {
                        releaseCheckout();
                        showFeedback('Razorpay did not return a complete payment result. Check the transaction before retrying.', true);
                        return;
                    }
                    fields.forEach(name => { verificationForm.elements.namedItem(name).value = response[name]; });
                    submitting = true;
                    showFeedback('Verifying the test payment with the server…');
                    // The POST response decides completion and redirects to the
                    // existing detail page. Never declare success in the browser.
                    verificationForm.requestSubmit();
                },
            });
            checkout.on('payment.failed', () => {
                showFeedback('The test payment did not complete. Retry in Razorpay or close checkout. No successful payment was recorded here.', true);
            });
            checkout.open();
        } catch (_) {
            releaseCheckout();
            showFeedback('Razorpay checkout could not open. Reload this page and try again. No payment was submitted.', true);
        }
    });
})();
