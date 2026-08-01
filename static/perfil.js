(() => {
    const dialog = document.getElementById('avatar-dialog');
    const openButton = document.getElementById('avatar-dialog-open');
    const closeButton = document.getElementById('avatar-dialog-close');
    const cancelButton = document.getElementById('avatar-dialog-cancel');
    const form = document.getElementById('avatar-form');
    const saveButton = document.getElementById('avatar-save-button');

    if (!dialog || !openButton || !form) return;

    const closeDialog = () => {
        if (typeof dialog.close === 'function') {
            dialog.close();
        } else {
            dialog.removeAttribute('open');
        }
        openButton.focus();
    };

    const syncSelection = () => {
        form.querySelectorAll('.avatar-option').forEach((option) => {
            const input = option.querySelector('input[type="radio"]');
            option.classList.toggle('is-selected', Boolean(input?.checked));
        });
    };

    openButton.addEventListener('click', () => {
        if (typeof dialog.showModal === 'function') {
            dialog.showModal();
        } else {
            dialog.setAttribute('open', '');
        }
        const selected = form.querySelector('input[name="avatar"]:checked');
        selected?.focus();
    });

    closeButton?.addEventListener('click', closeDialog);
    cancelButton?.addEventListener('click', closeDialog);

    form.querySelectorAll('input[name="avatar"]').forEach((input) => {
        input.addEventListener('change', syncSelection);
    });

    dialog.addEventListener('click', (event) => {
        const bounds = dialog.getBoundingClientRect();
        const outside = (
            event.clientX < bounds.left ||
            event.clientX > bounds.right ||
            event.clientY < bounds.top ||
            event.clientY > bounds.bottom
        );
        if (outside) closeDialog();
    });

    form.addEventListener('submit', () => {
        if (!saveButton) return;
        saveButton.disabled = true;
        saveButton.textContent = 'Guardando…';
    });

    syncSelection();
})();
