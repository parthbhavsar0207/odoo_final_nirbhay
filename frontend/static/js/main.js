/**
 * Champions Club - Client Interactions
 * Minimal Alpine/HTMX helper script
 */

document.addEventListener('DOMContentLoaded', () => {
    // Setup csrf token for HTMX requests
    document.body.addEventListener('htmx:configRequest', (event) => {
        const getCookie = (name) => {
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        };
        
        const csrfToken = getCookie('csrftoken');
        if (csrfToken) {
            event.detail.headers['X-CSRFToken'] = csrfToken;
        }
    });

    console.log('Champions Club scaffold initialized. Ready for module integrations.');
});
