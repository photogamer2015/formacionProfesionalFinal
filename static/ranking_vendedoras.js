(function () {
    'use strict';

    const picker = document.querySelector('[data-ranking-date-picker]');
    if (!picker) return;

    const trigger = picker.querySelector('[data-date-trigger]');
    const triggerText = picker.querySelector('[data-date-trigger-text]');
    const popover = picker.querySelector('[data-date-popover]');
    const startInput = picker.querySelector('[data-date-start]');
    const endInput = picker.querySelector('[data-date-end]');
    const rangeModeInput = picker.querySelector('[data-date-range-mode]');
    const clearButton = picker.querySelector('[data-date-clear]');
    const cancelButton = picker.querySelector('[data-date-cancel]');
    const acceptButton = picker.querySelector('[data-date-accept]');
    const hint = picker.querySelector('[data-date-hint]');
    const presetButtons = Array.from(picker.querySelectorAll('[data-date-preset]'));
    const calendarContainers = Array.from(picker.querySelectorAll('[data-date-calendar]'));
    const defaultLabel = picker.dataset.defaultLabel || 'Fecha';

    const shortMonths = [
        'ene', 'feb', 'mar', 'abr', 'may', 'jun',
        'jul', 'ago', 'sep', 'oct', 'nov', 'dic',
    ];
    const fullMonths = [
        'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
    ];
    const weekDays = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];

    let draftStart = null;
    let draftEnd = null;
    let rangeMode = false;
    let baseYear = getToday().getFullYear();
    let baseMonth = getToday().getMonth();

    function pad(value) {
        return String(value).padStart(2, '0');
    }

    function toISO(date) {
        if (!date) return '';
        return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
    }

    function parseISO(value) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return null;
        const parts = value.split('-').map(Number);
        const date = new Date(parts[0], parts[1] - 1, parts[2]);
        if (
            date.getFullYear() !== parts[0]
            || date.getMonth() !== parts[1] - 1
            || date.getDate() !== parts[2]
        ) {
            return null;
        }
        return date;
    }

    function getToday() {
        const now = new Date();
        return new Date(now.getFullYear(), now.getMonth(), now.getDate());
    }

    function cloneDate(date) {
        return date ? new Date(date.getFullYear(), date.getMonth(), date.getDate()) : null;
    }

    function addDays(date, days) {
        const result = cloneDate(date);
        result.setDate(result.getDate() + days);
        return result;
    }

    function sameDate(first, second) {
        return Boolean(first && second && toISO(first) === toISO(second));
    }

    function compareDates(first, second) {
        return toISO(first).localeCompare(toISO(second));
    }

    function startOfWeek(date) {
        const result = cloneDate(date);
        const mondayOffset = (result.getDay() + 6) % 7;
        result.setDate(result.getDate() - mondayOffset);
        return result;
    }

    function formatDate(date) {
        return date.getDate() + ' ' + shortMonths[date.getMonth()] + ' ' + date.getFullYear();
    }

    function getPreset(key) {
        const today = getToday();
        if (key === 'all') return { start: null, end: null };
        if (key === 'today') return { start: today, end: today };
        if (key === 'yesterday') {
            const yesterday = addDays(today, -1);
            return { start: yesterday, end: yesterday };
        }
        if (key === 'last7') return { start: addDays(today, -6), end: today };
        if (key === 'last14') return { start: addDays(today, -13), end: today };
        if (key === 'last30') return { start: addDays(today, -29), end: today };
        if (key === 'thisWeek') {
            const start = startOfWeek(today);
            return { start: start, end: addDays(start, 6) };
        }
        if (key === 'thisMonth') {
            return {
                start: new Date(today.getFullYear(), today.getMonth(), 1),
                end: new Date(today.getFullYear(), today.getMonth() + 1, 0),
            };
        }
        if (key === 'lastMonth') {
            return {
                start: new Date(today.getFullYear(), today.getMonth() - 1, 1),
                end: new Date(today.getFullYear(), today.getMonth(), 0),
            };
        }
        return { start: null, end: null };
    }

    function updateAppliedLabel() {
        const start = parseISO(startInput.value);
        const end = parseISO(endInput.value);
        let label = defaultLabel;

        if (start && end) {
            label = sameDate(start, end)
                ? defaultLabel + ': ' + formatDate(start)
                : formatDate(start) + ' — ' + formatDate(end);
        } else if (start) {
            label = 'Desde ' + formatDate(start);
        } else if (end) {
            label = 'Hasta ' + formatDate(end);
        }

        triggerText.textContent = label;
        picker.classList.toggle('has-value', Boolean(start || end));
    }

    function normalizeDraft() {
        if (draftStart && draftEnd && compareDates(draftStart, draftEnd) > 0) {
            const previousStart = draftStart;
            draftStart = draftEnd;
            draftEnd = previousStart;
        }
    }

    function setViewFromDraft() {
        const reference = draftStart || draftEnd || getToday();
        baseYear = reference.getFullYear();
        baseMonth = reference.getMonth();
    }

    function renderPresetState() {
        presetButtons.forEach(function (button) {
            const preset = getPreset(button.dataset.datePreset);
            const active = (
                (!draftStart && !draftEnd && !preset.start && !preset.end)
                || (sameDate(draftStart, preset.start) && sameDate(draftEnd, preset.end))
            );
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    }

    function renderHint() {
        if (!draftStart && !draftEnd) {
            hint.textContent = 'Selecciona una fecha o usa uno de los rangos rápidos.';
        } else if (rangeMode && draftStart && !draftEnd) {
            hint.textContent = 'Ahora selecciona la fecha final del rango.';
        } else if (draftStart && draftEnd && !sameDate(draftStart, draftEnd)) {
            hint.textContent = formatDate(draftStart) + ' — ' + formatDate(draftEnd);
        } else {
            hint.textContent = formatDate(draftStart || draftEnd);
        }
    }

    function renderCalendar(container, offset) {
        const monthDate = new Date(baseYear, baseMonth + offset, 1);
        const year = monthDate.getFullYear();
        const month = monthDate.getMonth();
        const leadingDays = (monthDate.getDay() + 6) % 7;
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        const todayISO = toISO(getToday());
        let html = '<div class="ranking-date-calendar-head">';

        html += offset === 0
            ? '<button type="button" class="ranking-date-nav" data-date-nav="-1" aria-label="Mes anterior">‹</button>'
            : '<span aria-hidden="true"></span>';
        html += '<div class="ranking-date-calendar-title">' + fullMonths[month] + ' ' + year + '</div>';
        html += offset === 1
            ? '<button type="button" class="ranking-date-nav" data-date-nav="1" aria-label="Mes siguiente">›</button>'
            : '<span aria-hidden="true"></span>';
        html += '</div>';
        html += '<div class="ranking-date-weekdays" aria-hidden="true">';
        html += weekDays.map(function (day) { return '<span>' + day + '</span>'; }).join('');
        html += '</div><div class="ranking-date-days">';

        for (let empty = 0; empty < leadingDays; empty += 1) {
            html += '<span class="ranking-date-empty-day" aria-hidden="true"></span>';
        }

        for (let day = 1; day <= daysInMonth; day += 1) {
            const date = new Date(year, month, day);
            const iso = toISO(date);
            const isStart = sameDate(date, draftStart);
            const isEnd = sameDate(date, draftEnd);
            const isInRange = Boolean(
                draftStart
                && draftEnd
                && compareDates(date, draftStart) >= 0
                && compareDates(date, draftEnd) <= 0
            );
            const classes = [
                'ranking-date-day',
                iso === todayISO ? 'is-today' : '',
                isInRange ? 'is-in-range' : '',
                isStart ? 'is-start' : '',
                isEnd ? 'is-end' : '',
            ].filter(Boolean).join(' ');
            const selected = isStart || isEnd ? ' aria-pressed="true"' : ' aria-pressed="false"';
            html += '<button type="button" class="' + classes + '" data-date-value="' + iso + '"' + selected + '>' + day + '</button>';
        }

        html += '</div>';
        container.innerHTML = html;
    }

    function render() {
        normalizeDraft();
        calendarContainers.forEach(function (container) {
            renderCalendar(container, Number(container.dataset.dateCalendar || 0));
        });
        renderPresetState();
        renderHint();
    }

    function positionPopover() {
        if (window.innerWidth <= 760) return;
        popover.style.left = '0px';
        const rect = popover.getBoundingClientRect();
        const availableRight = window.innerWidth - 16;
        if (rect.right > availableRight) {
            popover.style.left = '-' + (rect.right - availableRight) + 'px';
        }
        const adjusted = popover.getBoundingClientRect();
        if (adjusted.left < 12) {
            const currentLeft = Number.parseFloat(popover.style.left || '0') || 0;
            popover.style.left = (currentLeft + 12 - adjusted.left) + 'px';
        }
    }

    function openPicker() {
        draftStart = parseISO(startInput.value);
        draftEnd = parseISO(endInput.value);
        normalizeDraft();
        rangeMode = Boolean(draftStart && draftEnd && !sameDate(draftStart, draftEnd));
        rangeModeInput.checked = rangeMode;
        setViewFromDraft();
        popover.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        render();
        positionPopover();
    }

    function closePicker(restoreFocus) {
        popover.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        if (restoreFocus) trigger.focus();
    }

    function selectDate(selected) {
        if (!rangeMode) {
            draftStart = selected;
            draftEnd = cloneDate(selected);
        } else if (!draftStart || draftEnd) {
            draftStart = selected;
            draftEnd = null;
        } else if (compareDates(selected, draftStart) < 0) {
            draftEnd = draftStart;
            draftStart = selected;
        } else {
            draftEnd = selected;
        }
        render();
    }

    trigger.addEventListener('click', function () {
        if (popover.hidden) openPicker();
        else closePicker(false);
    });

    popover.addEventListener('click', function (event) {
        event.stopPropagation();

        const dateButton = event.target.closest('[data-date-value]');
        if (dateButton) {
            selectDate(parseISO(dateButton.dataset.dateValue));
            return;
        }

        const navButton = event.target.closest('[data-date-nav]');
        if (navButton) {
            const nextMonth = new Date(baseYear, baseMonth + Number(navButton.dataset.dateNav), 1);
            baseYear = nextMonth.getFullYear();
            baseMonth = nextMonth.getMonth();
            render();
            return;
        }

        const presetButton = event.target.closest('[data-date-preset]');
        if (presetButton) {
            const preset = getPreset(presetButton.dataset.datePreset);
            draftStart = cloneDate(preset.start);
            draftEnd = cloneDate(preset.end);
            rangeMode = Boolean(draftStart && draftEnd && !sameDate(draftStart, draftEnd));
            rangeModeInput.checked = rangeMode;
            setViewFromDraft();
            render();
        }
    });

    rangeModeInput.addEventListener('change', function () {
        rangeMode = rangeModeInput.checked;
        if (!rangeMode && draftStart) draftEnd = cloneDate(draftStart);
        render();
    });

    clearButton.addEventListener('click', function () {
        draftStart = null;
        draftEnd = null;
        rangeMode = false;
        rangeModeInput.checked = false;
        setViewFromDraft();
        render();
    });

    cancelButton.addEventListener('click', function () {
        closePicker(true);
    });

    acceptButton.addEventListener('click', function () {
        if (draftStart && !draftEnd) draftEnd = cloneDate(draftStart);
        if (!draftStart && draftEnd) draftStart = cloneDate(draftEnd);
        normalizeDraft();
        startInput.value = toISO(draftStart);
        endInput.value = toISO(draftEnd);
        updateAppliedLabel();
        closePicker(true);
    });

    document.addEventListener('click', function (event) {
        if (!popover.hidden && !picker.contains(event.target)) {
            closePicker(false);
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !popover.hidden) {
            closePicker(true);
        }
    });

    window.addEventListener('resize', function () {
        if (!popover.hidden) positionPopover();
    });

    updateAppliedLabel();
}());
