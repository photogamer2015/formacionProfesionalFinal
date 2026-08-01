(() => {
    const showDialog = (dialog) => {
        if (typeof dialog.showModal === 'function') {
            dialog.showModal();
        } else {
            dialog.setAttribute('open', '');
        }
    };

    const hideDialog = (dialog) => {
        if (typeof dialog.close === 'function' && dialog.open) {
            dialog.close();
        } else {
            dialog.removeAttribute('open');
        }
    };

    const clickedOutsideDialog = (dialog, event) => {
        const bounds = dialog.getBoundingClientRect();
        return (
            event.clientX < bounds.left ||
            event.clientX > bounds.right ||
            event.clientY < bounds.top ||
            event.clientY > bounds.bottom
        );
    };

    const initChoiceDialog = ({
        dialogId,
        openId,
        closeId,
        cancelId,
        formId,
        saveId,
        inputName,
        optionSelector,
        savingText,
    }) => {
        const dialog = document.getElementById(dialogId);
        const openButton = document.getElementById(openId);
        const closeButton = document.getElementById(closeId);
        const cancelButton = document.getElementById(cancelId);
        const form = document.getElementById(formId);
        const saveButton = document.getElementById(saveId);

        if (!dialog || !openButton || !form) return;

        const closeDialog = () => {
            hideDialog(dialog);
            openButton.focus();
        };

        const syncSelection = () => {
            form.querySelectorAll(optionSelector).forEach((option) => {
                const input = option.querySelector('input[type="radio"]');
                option.classList.toggle('is-selected', Boolean(input?.checked));
            });
        };

        openButton.addEventListener('click', () => {
            showDialog(dialog);
            form.querySelector(`input[name="${inputName}"]:checked`)?.focus();
        });

        closeButton?.addEventListener('click', closeDialog);
        cancelButton?.addEventListener('click', closeDialog);

        form.querySelectorAll(`input[name="${inputName}"]`).forEach((input) => {
            input.addEventListener('change', syncSelection);
        });

        dialog.addEventListener('click', (event) => {
            if (clickedOutsideDialog(dialog, event)) closeDialog();
        });

        form.addEventListener('submit', () => {
            if (!saveButton) return;
            saveButton.disabled = true;
            saveButton.textContent = savingText;
        });

        syncSelection();
    };

    initChoiceDialog({
        dialogId: 'avatar-dialog',
        openId: 'avatar-dialog-open',
        closeId: 'avatar-dialog-close',
        cancelId: 'avatar-dialog-cancel',
        formId: 'avatar-form',
        saveId: 'avatar-save-button',
        inputName: 'avatar',
        optionSelector: '.avatar-option',
        savingText: 'Guardando…',
    });

    initChoiceDialog({
        dialogId: 'cover-dialog',
        openId: 'cover-dialog-open',
        closeId: 'cover-dialog-close',
        cancelId: 'cover-dialog-cancel',
        formId: 'cover-form',
        saveId: 'cover-save-button',
        inputName: 'portada',
        optionSelector: '.cover-option',
        savingText: 'Guardando…',
    });

    const summaryDialog = document.getElementById('profile-summary-dialog');
    const summaryTitle = document.getElementById('profile-summary-dialog-title');
    const summaryContent = document.getElementById('profile-summary-dialog-content');
    let summaryReturnFocus = null;

    if (summaryDialog && summaryTitle && summaryContent) {
        const closeSummary = () => {
            hideDialog(summaryDialog);
            summaryReturnFocus?.focus();
        };

        document.querySelectorAll('[data-summary-target]').forEach((button) => {
            button.addEventListener('click', () => {
                const template = document.getElementById(button.dataset.summaryTarget || '');
                if (!(template instanceof HTMLTemplateElement)) return;

                summaryReturnFocus = button;
                summaryTitle.textContent = button.dataset.summaryTitle || 'Detalle de estudiantes';
                summaryContent.replaceChildren(template.content.cloneNode(true));
                showDialog(summaryDialog);
                summaryDialog.querySelector('[data-summary-close]')?.focus();
            });
        });

        summaryDialog.querySelectorAll('[data-summary-close]').forEach((button) => {
            button.addEventListener('click', closeSummary);
        });

        summaryDialog.addEventListener('click', (event) => {
            if (clickedOutsideDialog(summaryDialog, event)) closeSummary();
        });
    }
})();
