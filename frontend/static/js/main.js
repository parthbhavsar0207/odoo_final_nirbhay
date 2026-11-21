/**
 * Champions Club - Client Interactions & Custom Accessible Select System
 * Minimal Alpine/HTMX helper script & custom dropdown/combobox controller
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

/* ==========================================================================
   Accessible Custom Select / Combobox Component
   Replaces OS-rendered native option menus with polished Champions Club design
   ========================================================================== */

let championsSelectCounter = 0;

function initChampionsDropdown(selectEl) {
    if (!selectEl || selectEl.dataset.championsSelectInitialized === 'true') {
        return;
    }
    if (selectEl.tagName !== 'SELECT') {
        return;
    }

    championsSelectCounter++;
    const uniqueId = selectEl.id || `champions-select-${championsSelectCounter}`;
    const isFilter = selectEl.classList.contains('filter-select') || !!selectEl.closest('.filter-control-bar, form[method="get"]');

    // 1. Create Wrapper Container
    const wrapper = document.createElement('div');
    wrapper.className = 'champions-select-wrapper';
    if (isFilter) {
        wrapper.classList.add('is-filter');
    }
    if (selectEl.disabled) {
        wrapper.classList.add('is-disabled');
    }

    // Insert wrapper in DOM before the select, then move select inside
    const parent = selectEl.parentNode;
    parent.insertBefore(wrapper, selectEl);
    wrapper.appendChild(selectEl);

    // Style native select so it's visually hidden but fully accessible to form submission and screen readers
    selectEl.classList.add('champions-select-native');
    selectEl.dataset.championsSelectInitialized = 'true';
    selectEl.setAttribute('tabindex', '-1');
    selectEl.setAttribute('aria-hidden', 'true');

    // Find any existing label for accessible naming
    let labelText = '';
    const labelEl = document.querySelector(`label[for="${selectEl.id}"]`) || selectEl.closest('label');
    if (labelEl) {
        labelText = labelEl.textContent.trim().replace(/[*:]/g, '').trim();
    }

    // 2. Create Trigger Button
    const triggerBtn = document.createElement('button');
    triggerBtn.type = 'button';
    triggerBtn.className = 'champions-select-trigger';
    triggerBtn.setAttribute('role', 'combobox');
    triggerBtn.setAttribute('aria-haspopup', 'listbox');
    triggerBtn.setAttribute('aria-expanded', 'false');
    triggerBtn.setAttribute('aria-controls', `listbox-${uniqueId}`);
    triggerBtn.id = `trigger-${uniqueId}`;
    if (selectEl.disabled) {
        triggerBtn.disabled = true;
    }
    if (labelText) {
        triggerBtn.setAttribute('aria-label', labelText);
    }

    const valueSpan = document.createElement('span');
    valueSpan.className = 'champions-select-value';
    triggerBtn.appendChild(valueSpan);

    const chevronIcon = document.createElement('span');
    chevronIcon.className = 'material-symbols-outlined champions-select-chevron';
    chevronIcon.setAttribute('aria-hidden', 'true');
    chevronIcon.textContent = 'expand_more';
    triggerBtn.appendChild(chevronIcon);

    wrapper.appendChild(triggerBtn);

    // 3. Create Floating Menu / Listbox
    const menuDiv = document.createElement('div');
    menuDiv.className = 'champions-select-menu';
    menuDiv.id = `listbox-${uniqueId}`;
    menuDiv.setAttribute('role', 'listbox');
    menuDiv.setAttribute('tabindex', '-1');
    if (labelText) {
        menuDiv.setAttribute('aria-label', labelText);
    }

    const optionsList = document.createElement('ul');
    optionsList.className = 'champions-select-options';
    menuDiv.appendChild(optionsList);

    wrapper.appendChild(menuDiv);

    // State
    let isOpen = false;
    let highlightedIndex = -1;
    let typeBuffer = '';
    let typeTimeout = null;

    function buildOptions() {
        optionsList.innerHTML = '';
        Array.from(selectEl.options).forEach((opt, index) => {
            const li = document.createElement('li');
            li.className = 'champions-select-option';
            li.id = `opt-${uniqueId}-${index}`;
            li.setAttribute('role', 'option');
            li.dataset.value = opt.value;
            li.dataset.index = index;

            const isSelected = opt.selected || selectEl.value === opt.value;
            li.setAttribute('aria-selected', isSelected ? 'true' : 'false');

            if (opt.disabled) {
                li.dataset.disabled = 'true';
                li.setAttribute('aria-disabled', 'true');
            }

            // Display text
            const textSpan = document.createElement('span');
            textSpan.className = 'champions-option-text';
            let label = opt.text;
            if (label === '---------') {
                label = 'Select an option...';
            }
            textSpan.textContent = label;
            li.appendChild(textSpan);

            // Checkmark icon
            const checkSpan = document.createElement('span');
            checkSpan.className = 'material-symbols-outlined champions-option-check';
            checkSpan.setAttribute('aria-hidden', 'true');
            checkSpan.textContent = 'check';
            li.appendChild(checkSpan);

            // Click option to select
            li.addEventListener('click', (e) => {
                e.stopPropagation();
                if (opt.disabled) return;
                selectValue(opt.value);
            });

            // Hover highlights option
            li.addEventListener('mouseenter', () => {
                if (opt.disabled) return;
                setHighlight(index);
            });

            optionsList.appendChild(li);
        });
    }

    function syncFromNative() {
        const currentVal = selectEl.value;
        const selectedOpt = selectEl.options[selectEl.selectedIndex] || selectEl.options[0];
        
        let displayLabel = selectedOpt ? selectedOpt.text : 'Select...';
        if (displayLabel === '---------') {
            displayLabel = 'Select an option...';
        }
        valueSpan.textContent = displayLabel;

        const isNoneOrEmpty = !currentVal && currentVal !== 0;
        if (isNoneOrEmpty && (displayLabel.startsWith('Select') || displayLabel === '---------')) {
            valueSpan.classList.add('is-placeholder');
        } else {
            valueSpan.classList.remove('is-placeholder');
        }

        const items = optionsList.querySelectorAll('.champions-select-option');
        items.forEach(li => {
            const isMatch = li.dataset.value === String(currentVal);
            li.setAttribute('aria-selected', isMatch ? 'true' : 'false');
        });
    }

    function checkPosition() {
        const rect = triggerBtn.getBoundingClientRect();
        const spaceBelow = window.innerHeight - rect.bottom;
        const spaceAbove = rect.top;
        if (spaceBelow < 280 && spaceAbove > spaceBelow) {
            wrapper.classList.add('dropdown-menu-up');
        } else {
            wrapper.classList.remove('dropdown-menu-up');
        }
    }

    function openMenu() {
        if (selectEl.disabled || isOpen) return;

        // Close any other open champions-dropdown in document
        document.querySelectorAll('.champions-select-wrapper.is-open').forEach(w => {
            if (w !== wrapper && w._championsClose) {
                w._championsClose();
            }
        });

        checkPosition();
        isOpen = true;
        wrapper.classList.add('is-open');
        triggerBtn.setAttribute('aria-expanded', 'true');

        // Highlight currently selected item
        const curIndex = selectEl.selectedIndex >= 0 ? selectEl.selectedIndex : 0;
        setHighlight(curIndex);
        scrollToHighlight();

        // Listen for outside click
        setTimeout(() => {
            document.addEventListener('click', onDocClick);
        }, 10);
    }

    function closeMenu() {
        if (!isOpen) return;
        isOpen = false;
        wrapper.classList.remove('is-open', 'dropdown-menu-up');
        triggerBtn.setAttribute('aria-expanded', 'false');
        clearHighlight();
        document.removeEventListener('click', onDocClick);
    }

    wrapper._championsClose = closeMenu;

    function onDocClick(e) {
        if (!wrapper.contains(e.target)) {
            closeMenu();
        }
    }

    function toggleMenu() {
        if (isOpen) {
            closeMenu();
        } else {
            openMenu();
        }
    }

    function setHighlight(index) {
        const items = optionsList.querySelectorAll('.champions-select-option');
        if (index < 0 || index >= items.length) return;
        
        items.forEach((item, i) => {
            if (i === index && item.dataset.disabled !== 'true') {
                item.classList.add('is-highlighted');
                triggerBtn.setAttribute('aria-activedescendant', item.id);
                highlightedIndex = i;
            } else {
                item.classList.remove('is-highlighted');
            }
        });
    }

    function clearHighlight() {
        const items = optionsList.querySelectorAll('.champions-select-option');
        items.forEach(item => item.classList.remove('is-highlighted'));
        triggerBtn.removeAttribute('aria-activedescendant');
        highlightedIndex = -1;
    }

    function scrollToHighlight() {
        const items = optionsList.querySelectorAll('.champions-select-option');
        if (highlightedIndex >= 0 && items[highlightedIndex]) {
            items[highlightedIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    function selectValue(newVal) {
        if (selectEl.value !== String(newVal)) {
            selectEl.value = newVal;
            syncFromNative();
            // Dispatch standard events so onchange and reactive frameworks react
            selectEl.dispatchEvent(new Event('change', { bubbles: true }));
            selectEl.dispatchEvent(new Event('input', { bubbles: true }));
        }
        closeMenu();
        triggerBtn.focus();
    }

    // Trigger click
    triggerBtn.addEventListener('click', (e) => {
        e.preventDefault();
        toggleMenu();
    });

    // Keyboard navigation
    triggerBtn.addEventListener('keydown', (e) => {
        const allItems = Array.from(optionsList.querySelectorAll('.champions-select-option'));

        if (!isOpen) {
            if (['ArrowDown', 'ArrowUp', ' ', 'Enter'].includes(e.key)) {
                e.preventDefault();
                openMenu();
                return;
            }
        }

        if (isOpen) {
            if (e.key === 'Escape') {
                e.preventDefault();
                closeMenu();
                triggerBtn.focus();
                return;
            }

            if (e.key === 'Tab') {
                closeMenu();
                return;
            }

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                let nextIdx = highlightedIndex + 1;
                while (nextIdx < allItems.length && allItems[nextIdx].dataset.disabled === 'true') {
                    nextIdx++;
                }
                if (nextIdx < allItems.length) {
                    setHighlight(nextIdx);
                    scrollToHighlight();
                }
                return;
            }

            if (e.key === 'ArrowUp') {
                e.preventDefault();
                let prevIdx = highlightedIndex - 1;
                while (prevIdx >= 0 && allItems[prevIdx].dataset.disabled === 'true') {
                    prevIdx--;
                }
                if (prevIdx >= 0) {
                    setHighlight(prevIdx);
                    scrollToHighlight();
                }
                return;
            }

            if (e.key === 'Home') {
                e.preventDefault();
                const firstEnabled = allItems.findIndex(it => it.dataset.disabled !== 'true');
                if (firstEnabled >= 0) {
                    setHighlight(firstEnabled);
                    scrollToHighlight();
                }
                return;
            }

            if (e.key === 'End') {
                e.preventDefault();
                for (let i = allItems.length - 1; i >= 0; i--) {
                    if (allItems[i].dataset.disabled !== 'true') {
                        setHighlight(i);
                        scrollToHighlight();
                        break;
                    }
                }
                return;
            }

            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                if (highlightedIndex >= 0 && allItems[highlightedIndex] && allItems[highlightedIndex].dataset.disabled !== 'true') {
                    selectValue(allItems[highlightedIndex].dataset.value);
                } else {
                    closeMenu();
                }
                return;
            }

            // Type-to-select
            if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                clearTimeout(typeTimeout);
                typeBuffer += e.key.toLowerCase();
                typeTimeout = setTimeout(() => {
                    typeBuffer = '';
                }, 500);

                const matchIdx = allItems.findIndex(it => {
                    if (it.dataset.disabled === 'true') return false;
                    const text = it.querySelector('.champions-option-text')?.textContent.trim().toLowerCase() || '';
                    return text.startsWith(typeBuffer);
                });

                if (matchIdx >= 0) {
                    setHighlight(matchIdx);
                    scrollToHighlight();
                }
            }
        }
    });

    // Label click refocus
    selectEl.addEventListener('focus', () => {
        triggerBtn.focus();
    });

    // Intercept programmatic property assignments like `product.value = ...` in commerce.js
    try {
        const originalDescriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
        if (originalDescriptor && originalDescriptor.set) {
            Object.defineProperty(selectEl, 'value', {
                get() {
                    return originalDescriptor.get.call(this);
                },
                set(val) {
                    originalDescriptor.set.call(this, val);
                    syncFromNative();
                },
                configurable: true
            });
        }
    } catch (err) {
        // Fallback gracefully
    }

    // Listen to native events
    selectEl.addEventListener('change', syncFromNative);
    selectEl.addEventListener('input', syncFromNative);

    // Watch for dynamic option updates
    const observer = new MutationObserver(() => {
        buildOptions();
        syncFromNative();
    });
    observer.observe(selectEl, { childList: true });

    // Initial build
    buildOptions();
    syncFromNative();
}

function initAllChampionsDropdowns(root = document) {
    if (!root || !root.querySelectorAll) return;
    const selects = root.querySelectorAll('select.form-select, .commerce-field select, select:not([data-no-custom])');
    selects.forEach(sel => {
        // Skip Django admin or explicitly excluded selects
        if (sel.closest('.admin-select, [data-no-custom]')) return;
        initChampionsDropdown(sel);
    });
}

// Window resize & scroll reposition check
window.addEventListener('resize', () => {
    document.querySelectorAll('.champions-select-wrapper.is-open').forEach(w => {
        if (w._championsClose) w._championsClose();
    });
});

// Auto-run on DOMContentLoaded, alpine:init, and htmx events
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initAllChampionsDropdowns());
} else {
    initAllChampionsDropdowns();
}

document.addEventListener('alpine:init', () => {
    if (window.Alpine) {
        Alpine.data('championsSelect', () => ({}));

        // Site Search Suggestions Component (Debounced, Accessible Keyboard Navigation)
        Alpine.data('siteSearch', () => ({
            query: '',
            suggestions: [],
            isOpen: false,
            selectedIndex: -1,
            isLoading: false,
            debounceTimer: null,

            onInput() {
                clearTimeout(this.debounceTimer);
                const q = this.query.trim();
                if (q.length < 1) {
                    this.suggestions = [];
                    this.isOpen = false;
                    this.selectedIndex = -1;
                    return;
                }

                this.debounceTimer = setTimeout(() => {
                    this.fetchSuggestions(q);
                }, 250);
            },

            async fetchSuggestions(q) {
                this.isLoading = true;
                try {
                    const resp = await fetch(`/club/api/suggestions/?q=${encodeURIComponent(q)}`);
                    const data = await resp.json();
                    this.suggestions = data.suggestions || [];
                    this.isOpen = true;
                    this.selectedIndex = -1;
                } catch (e) {
                    console.error('Search suggestions error:', e);
                    this.suggestions = [];
                } finally {
                    this.isLoading = false;
                }
            },

            onKeyDown(e) {
                if (!this.isOpen || this.suggestions.length === 0) {
                    if (e.key === 'Escape') this.close();
                    return;
                }

                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this.selectedIndex = (this.selectedIndex + 1) % this.suggestions.length;
                    this.scrollToSelected();
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this.selectedIndex = (this.selectedIndex - 1 + this.suggestions.length) % this.suggestions.length;
                    this.scrollToSelected();
                } else if (e.key === 'Enter') {
                    if (this.selectedIndex >= 0 && this.suggestions[this.selectedIndex]) {
                        e.preventDefault();
                        window.location.href = this.suggestions[this.selectedIndex].url;
                    }
                } else if (e.key === 'Escape') {
                    e.preventDefault();
                    this.close();
                }
            },

            scrollToSelected() {
                this.$nextTick(() => {
                    const container = this.$refs.suggestionsList;
                    if (!container) return;
                    const activeItem = container.querySelector('.is-highlighted');
                    if (activeItem) {
                        activeItem.scrollIntoView({ block: 'nearest' });
                    }
                });
            },

            selectItem(url) {
                window.location.href = url;
            },

            close() {
                this.isOpen = false;
                this.selectedIndex = -1;
            }
        }));

        // Help Chatbot & Guided FAQ Assistant Component
        Alpine.data('helpBot', () => ({
            isOpen: false,
            inputQuery: '',
            isLoading: false,
            messages: [
                {
                    role: 'agent',
                    text: 'Hello! I am your Champions Club Concierge. How can I assist you with sports, court reservations, or membership plans today?',
                    chips: [
                        { label: '🎾 10 Sports & Facilities', query: 'sports' },
                        { label: '📅 Live Court Availability', query: 'availability' },
                        { label: '🏷️ Membership Plans & Perks', query: 'plans' },
                        { label: '⏰ Booking Rules & Hours', query: 'booking' },
                        { label: '☕ Pro Shop & Bar', query: 'commerce' },
                        { label: '📞 Front Desk Contact', query: 'contact' },
                    ]
                }
            ],

            toggle() {
                this.isOpen = !this.isOpen;
                if (this.isOpen) {
                    this.$nextTick(() => {
                        this.scrollToBottom();
                        if (this.$refs.chatInput) this.$refs.chatInput.focus();
                    });
                }
            },

            async ask(queryText) {
                const q = (queryText || this.inputQuery).trim();
                if (!q) return;

                this.messages.push({ role: 'user', text: q });
                this.inputQuery = '';
                this.isLoading = true;
                this.scrollToBottom();

                try {
                    const resp = await fetch(`/club/api/faq/?q=${encodeURIComponent(q)}`);
                    const data = await resp.json();

                    if (data.faqs && data.faqs.length > 0) {
                        const primary = data.faqs[0];
                        this.messages.push({
                            role: 'agent',
                            text: primary.answer,
                            actionLabel: primary.action_label,
                            actionUrl: primary.action_url,
                        });
                    } else if (data.fallback) {
                        this.messages.push({
                            role: 'agent',
                            text: data.fallback.message,
                            actionLabel: data.fallback.action_label,
                            actionUrl: data.fallback.action_url,
                        });
                    } else {
                        this.messages.push({
                            role: 'agent',
                            text: 'Our front desk concierge is on site daily 06:00 to 22:00. Contact operations@championsclub.com or +91 98765 43210 for personalized assistance.',
                            actionLabel: 'View Sports & Facilities',
                            actionUrl: '/club/sports/',
                        });
                    }
                } catch (e) {
                    console.error('FAQ Assistant error:', e);
                    this.messages.push({
                        role: 'agent',
                        text: 'For immediate assistance with bookings or facilities, please reach out to our front desk team at operations@championsclub.com or +91 98765 43210.',
                        actionLabel: 'View Sports & Facilities',
                        actionUrl: '/club/sports/',
                    });
                } finally {
                    this.isLoading = false;
                    this.scrollToBottom();
                }
            },

            scrollToBottom() {
                this.$nextTick(() => {
                    const body = this.$refs.chatBody;
                    if (body) body.scrollTop = body.scrollHeight;
                });
            }
        }));
    }
    initAllChampionsDropdowns();
});

document.addEventListener('htmx:load', (e) => {
    initAllChampionsDropdowns(e.detail?.elt || document);
});
document.addEventListener('htmx:afterSwap', (e) => {
    initAllChampionsDropdowns(e.detail?.target || document);
});

window.initChampionsDropdown = initChampionsDropdown;
window.initAllChampionsDropdowns = initAllChampionsDropdowns;

// ==========================================================================
// Quick Time Slot Selector & Live Session Preview Helper
// ==========================================================================
function initQuickSlotHelper() {
    const startInput = document.querySelector('input[name="start_datetime"]');
    const quickGrid = document.getElementById('quick-slots-grid');
    const timeDisplay = document.getElementById('session-time-display');
    const descDisplay = document.getElementById('session-desc-display');
    const statusBadge = document.getElementById('session-status-badge');
    const minuteToggles = document.querySelectorAll('.quick-minute-toggle');

    if (!startInput || !quickGrid) return;

    let selectedMinute = '00';

    function updateSessionPreview() {
        const val = startInput.value;
        if (!val) {
            if (timeDisplay) timeDisplay.textContent = 'Session: 60 Minutes';
            if (statusBadge) {
                statusBadge.textContent = 'Select Time';
                statusBadge.style.backgroundColor = 'var(--surface-container-low)';
                statusBadge.style.color = 'var(--secondary-stitch)';
            }
            return;
        }

        try {
            const startDate = new Date(val);
            if (isNaN(startDate.getTime())) return;

            const endDate = new Date(startDate.getTime() + 60 * 60 * 1000);
            const formatTime = (d) => {
                const h = String(d.getHours()).padStart(2, '0');
                const m = String(d.getMinutes()).padStart(2, '0');
                return `${h}:${m}`;
            };
            const formatDate = (d) => {
                const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
            };

            const startTimeStr = formatTime(startDate);
            const endTimeStr = formatTime(endDate);
            const dateStr = formatDate(startDate);

            if (timeDisplay) {
                timeDisplay.textContent = `Session: ${startTimeStr} – ${endTimeStr} (${dateStr})`;
            }

            const minutes = startDate.getMinutes();
            if (minutes === 0 || minutes === 30) {
                if (statusBadge) {
                    statusBadge.textContent = 'Valid 60m Slot';
                    statusBadge.style.backgroundColor = '#eaf8c7';
                    statusBadge.style.color = '#3b5000';
                }
                if (descDisplay) {
                    descDisplay.textContent = `Valid standard start time (${startTimeStr}). Duration: exactly 60 minutes. GiST constraint will verify court availability.`;
                }
            } else {
                if (statusBadge) {
                    statusBadge.textContent = `${minutes}m offset`;
                    statusBadge.style.backgroundColor = '#fef3c7';
                    statusBadge.style.color = '#92400e';
                }
                if (descDisplay) {
                    descDisplay.textContent = `Selected start is ${startTimeStr}. Champions Club standard sessions start on the hour (:00) or half-hour (:30).`;
                }
            }

            // Sync active state on quick buttons
            quickGrid.querySelectorAll('.quick-slot-btn').forEach(btn => {
                const targetTime = btn.dataset.time;
                if (targetTime === startTimeStr) {
                    btn.classList.add('is-selected');
                } else {
                    btn.classList.remove('is-selected');
                }
            });
        } catch (e) {
            console.error('Session preview error:', e);
        }
    }

    function setSlot(timeStr) {
        let currentDateStr = '';
        if (startInput.value && startInput.value.includes('T')) {
            currentDateStr = startInput.value.split('T')[0];
        } else {
            const today = new Date();
            const y = today.getFullYear();
            const m = String(today.getMonth() + 1).padStart(2, '0');
            const d = String(today.getDate()).padStart(2, '0');
            currentDateStr = `${y}-${m}-${d}`;
        }

        const newDateTimeVal = `${currentDateStr}T${timeStr}`;
        startInput.value = newDateTimeVal;
        startInput.dispatchEvent(new Event('input', { bubbles: true }));
        startInput.dispatchEvent(new Event('change', { bubbles: true }));
        updateSessionPreview();
    }

    // Minute toggles (:00 vs :30)
    minuteToggles.forEach(toggle => {
        toggle.addEventListener('click', () => {
            minuteToggles.forEach(t => t.classList.remove('is-active'));
            toggle.classList.add('is-active');
            selectedMinute = toggle.dataset.minute;

            // Update slot button labels and times
            quickGrid.querySelectorAll('.quick-slot-btn').forEach(btn => {
                const currentHour = btn.dataset.time.split(':')[0];
                const newTime = `${currentHour}:${selectedMinute}`;
                btn.dataset.time = newTime;
                btn.textContent = newTime;
            });

            // If an active button was clicked, update the input
            const activeBtn = quickGrid.querySelector('.quick-slot-btn.is-selected');
            if (activeBtn) {
                activeBtn.classList.remove('slot-pulse-active');
                void activeBtn.offsetWidth;
                activeBtn.classList.add('slot-pulse-active');
                setTimeout(() => activeBtn.classList.remove('slot-pulse-active'), 400);
                setSlot(activeBtn.dataset.time);
            }
        });
    });

    // Slot button clicks with restrained athletic highlight
    quickGrid.querySelectorAll('.quick-slot-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            quickGrid.querySelectorAll('.quick-slot-btn').forEach(b => b.classList.remove('is-selected'));
            btn.classList.add('is-selected');
            
            // Brief visual pulse on selected slot
            btn.classList.remove('slot-pulse-active');
            void btn.offsetWidth;
            btn.classList.add('slot-pulse-active');
            setTimeout(() => btn.classList.remove('slot-pulse-active'), 400);

            // Subtle confirmation flash on preview card
            const previewCard = document.querySelector('.session-preview-card');
            if (previewCard) {
                previewCard.classList.remove('session-card-flash');
                void previewCard.offsetWidth;
                previewCard.classList.add('session-card-flash');
            }

            setSlot(btn.dataset.time);
        });
    });

    startInput.addEventListener('input', updateSessionPreview);
    startInput.addEventListener('change', updateSessionPreview);

    updateSessionPreview();

    // If pre-filled from court matrix URL query (?start=...), highlight the matching slot
    if (window.location.search && window.location.search.includes('start=')) {
        setTimeout(() => {
            const selectedBtn = quickGrid.querySelector('.quick-slot-btn.is-selected');
            if (selectedBtn) {
                selectedBtn.classList.add('slot-pulse-active');
                setTimeout(() => selectedBtn.classList.remove('slot-pulse-active'), 500);
            }
        }, 100);
    }
}

// Attach to document events
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initQuickSlotHelper);
} else {
    initQuickSlotHelper();
}
document.addEventListener('htmx:load', initQuickSlotHelper);
