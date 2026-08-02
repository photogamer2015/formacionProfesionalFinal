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

    const muralForm = document.getElementById('profile-mural-form');
    const muralDescription = document.getElementById('profile-mural-description');
    const muralCounter = document.getElementById('profile-mural-counter');
    const muralSaveButton = document.getElementById('profile-mural-save');

    if (muralForm) {
        const updateCounter = () => {
            if (!muralDescription || !muralCounter) return;
            muralCounter.textContent = `${muralDescription.value.length}/500`;
        };

        muralForm.querySelectorAll('[data-choice-limit]').forEach((group) => {
            const limit = Number(group.dataset.choiceLimit || 6);
            const inputs = Array.from(group.querySelectorAll('input[type="checkbox"]'));
            const updateGroup = () => {
                const selected = inputs.filter((input) => input.checked).length;
                inputs.forEach((input) => {
                    input.disabled = !input.checked && selected >= limit;
                    input.closest('.profile-mural-choice')?.classList.toggle(
                        'is-selected',
                        input.checked,
                    );
                });
            };

            inputs.forEach((input) => input.addEventListener('change', updateGroup));
            updateGroup();
        });

        muralDescription?.addEventListener('input', updateCounter);
        muralForm.addEventListener('submit', () => {
            if (!muralSaveButton) return;
            muralSaveButton.disabled = true;
            muralSaveButton.textContent = 'Guardando…';
        });
        updateCounter();
    }

    const initSimpleProfileDialog = ({dialogId, openId, closeSelector}) => {
        const dialog = document.getElementById(dialogId);
        const openButton = document.getElementById(openId);
        if (!dialog || !openButton) return null;

        const closeDialog = () => {
            hideDialog(dialog);
            openButton.focus();
        };

        openButton.addEventListener('click', () => showDialog(dialog));
        dialog.querySelectorAll(closeSelector).forEach((button) => {
            button.addEventListener('click', closeDialog);
        });
        dialog.addEventListener('click', (event) => {
            if (clickedOutsideDialog(dialog, event)) closeDialog();
        });
        return {dialog, openButton, closeDialog};
    };

    initSimpleProfileDialog({
        dialogId: 'friends-dialog',
        openId: 'friends-dialog-open',
        closeSelector: '[data-friends-close]',
    });

    const friendSearch = initSimpleProfileDialog({
        dialogId: 'friend-search-dialog',
        openId: 'friend-search-open',
        closeSelector: '[data-friend-search-close]',
    });

    if (friendSearch) {
        const {dialog, openButton} = friendSearch;
        const form = document.getElementById('friend-search-form');
        const input = document.getElementById('friend-search-input');
        const status = document.getElementById('friend-search-status');
        const results = document.getElementById('friend-search-results');
        const csrfToken = form?.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
        let searchController = null;
        let searchTimer = null;
        let loadedOnce = false;

        const createActionForm = (url, action, label) => {
            const actionForm = document.createElement('form');
            actionForm.method = 'post';
            actionForm.action = url;

            const csrf = document.createElement('input');
            csrf.type = 'hidden';
            csrf.name = 'csrfmiddlewaretoken';
            csrf.value = csrfToken;
            actionForm.appendChild(csrf);

            if (action) {
                const actionInput = document.createElement('input');
                actionInput.type = 'hidden';
                actionInput.name = 'accion';
                actionInput.value = action;
                actionForm.appendChild(actionInput);
            }

            const button = document.createElement('button');
            button.type = 'submit';
            button.className = 'profile-search-result-action';
            button.textContent = label;
            actionForm.appendChild(button);
            return actionForm;
        };

        const renderResults = (items) => {
            results.replaceChildren();
            if (!items.length) {
                const empty = document.createElement('div');
                empty.className = 'profile-social-empty';
                const title = document.createElement('strong');
                title.textContent = 'No encontramos usuarios';
                const note = document.createElement('p');
                note.textContent = 'Prueba con otro nombre o usuario.';
                empty.append(title, note);
                results.appendChild(empty);
                return;
            }

            items.forEach((item) => {
                const row = document.createElement('article');
                row.className = 'profile-friend-search-item';

                const avatar = document.createElement('img');
                avatar.src = item.avatar;
                avatar.alt = '';
                avatar.setAttribute('aria-hidden', 'true');

                const identity = document.createElement('div');
                identity.className = 'profile-friend-search-identity';
                const name = document.createElement('strong');
                name.textContent = item.nombre;
                const meta = document.createElement('small');
                meta.textContent = `@${item.username} · ${item.rol}`;
                identity.append(name, meta);

                const actions = document.createElement('div');
                actions.className = 'profile-friend-search-actions';
                const profileLink = document.createElement('a');
                profileLink.href = item.perfil_url;
                profileLink.className = 'profile-search-profile-link';
                profileLink.textContent = 'Ver perfil';
                actions.appendChild(profileLink);

                if (item.estado === 'sin_relacion') {
                    actions.appendChild(createActionForm(
                        item.solicitar_url,
                        '',
                        'Añadir',
                    ));
                } else if (item.estado === 'solicitud_recibida') {
                    actions.appendChild(createActionForm(
                        item.accion_url,
                        'aceptar',
                        'Aceptar',
                    ));
                } else {
                    const state = document.createElement('span');
                    state.className = 'profile-search-result-state';
                    if (item.estado === 'amigos') {
                        state.classList.add('is-friend');
                        state.textContent = '✓ Amigos';
                    } else {
                        state.textContent = 'Solicitud enviada';
                    }
                    actions.appendChild(state);
                }

                row.append(avatar, identity, actions);
                results.appendChild(row);
            });
        };

        const loadFriends = async () => {
            searchController?.abort();
            searchController = new AbortController();
            status.textContent = 'Buscando usuarios…';

            const url = new URL(dialog.dataset.searchUrl, window.location.origin);
            url.searchParams.set('q', input.value.trim());

            try {
                const response = await fetch(url, {
                    headers: {'X-Requested-With': 'XMLHttpRequest'},
                    signal: searchController.signal,
                });
                if (!response.ok) throw new Error('search_failed');
                const data = await response.json();
                renderResults(data.resultados || []);
                status.textContent = data.resultados?.length
                    ? `${data.resultados.length} usuario${data.resultados.length === 1 ? '' : 's'} encontrado${data.resultados.length === 1 ? '' : 's'}.`
                    : '';
                loadedOnce = true;
            } catch (error) {
                if (error.name === 'AbortError') return;
                results.replaceChildren();
                status.textContent = 'No fue posible buscar usuarios. Intenta nuevamente.';
            }
        };

        openButton.addEventListener('click', () => {
            input?.focus();
            if (!loadedOnce) loadFriends();
        });
        form?.addEventListener('submit', (event) => {
            event.preventDefault();
            loadFriends();
        });
        input?.addEventListener('input', () => {
            window.clearTimeout(searchTimer);
            searchTimer = window.setTimeout(loadFriends, 260);
        });
    }

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
