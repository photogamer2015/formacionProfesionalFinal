(function () {
    "use strict";

    var TABLE_PAGE_SIZE = 10;
    var resizeObserver = null;
    var updateFrame = 0;
    var paginationSequence = 0;
    var paginationStates = new WeakMap();
    var navigationStates = new WeakMap();

    function tableLabel(table, index) {
        var explicitLabel = table.getAttribute("aria-label");
        if (explicitLabel) return explicitLabel;

        var caption = table.querySelector("caption");
        if (caption && caption.textContent.trim()) return caption.textContent.trim();

        var section = table.closest("section, article, .card-box, .card");
        var heading = section && section.querySelector("h2, h3, h4");
        if (heading && heading.textContent.trim()) return heading.textContent.trim();

        return "Tabla " + (index + 1);
    }

    function tableBodyRows(table) {
        var rows = [];
        Array.prototype.forEach.call(table.tBodies || [], function (tbody) {
            Array.prototype.forEach.call(tbody.rows || [], function (row) {
                rows.push(row);
            });
        });
        return rows;
    }

    function tablePageSize(table) {
        var configured = Number(
            table.dataset.tablePageSize || table.dataset.pageSize || TABLE_PAGE_SIZE
        );
        if (!Number.isFinite(configured)) return TABLE_PAGE_SIZE;
        configured = Math.floor(configured);
        if (configured < 1 || configured > 100) return TABLE_PAGE_SIZE;
        return configured;
    }

    function isEmptyStateRow(row) {
        if (row.dataset.paginationEmpty === "true") return true;
        if (row.cells.length !== 1 || !row.cells[0].hasAttribute("colspan")) {
            return false;
        }

        return /^(no hay|sin |a[uú]n no|ning[uú]n)/i.test(
            row.cells[0].textContent.trim()
        );
    }

    function isFilteredRow(row) {
        if (row.hidden || row.dataset.paginationFiltered === "true") return true;
        if (row.style && row.style.display === "none") return true;
        return window.getComputedStyle(row).display === "none";
    }

    function createPaginationButton(label, direction, tableId) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "fp-table-pagination__button";
        button.dataset.pageDirection = direction;
        button.setAttribute("aria-controls", tableId);
        button.setAttribute(
            "aria-label",
            direction === "previous" ? "Ir a la página anterior" : "Ir a la página siguiente"
        );

        var icon = document.createElement("span");
        icon.className = "fp-table-pagination__arrow";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = direction === "previous" ? "←" : "→";

        var text = document.createElement("span");
        text.textContent = label;

        if (direction === "previous") {
            button.appendChild(icon);
            button.appendChild(text);
        } else {
            button.appendChild(text);
            button.appendChild(icon);
        }
        return button;
    }

    function createTablePagination(table) {
        if (!table.id) {
            paginationSequence += 1;
            table.id = "fp-paginated-table-" + paginationSequence;
        }

        var pagination = document.createElement("nav");
        pagination.className = "fp-table-pagination";
        pagination.setAttribute("aria-label", "Paginación de " + tableLabel(table, 0));

        var summary = document.createElement("div");
        summary.className = "fp-table-pagination__summary";
        summary.innerHTML =
            '<span class="fp-table-pagination__summary-icon" aria-hidden="true">≡</span>' +
            '<span>Registros <strong data-page-range>0</strong> de ' +
            '<strong data-page-total>0</strong></span>';

        var controls = document.createElement("div");
        controls.className = "fp-table-pagination__controls";
        var previousButton = createPaginationButton("Anterior", "previous", table.id);
        var nextButton = createPaginationButton("Siguiente", "next", table.id);

        var indicator = document.createElement("span");
        indicator.className = "fp-table-pagination__indicator";
        indicator.setAttribute("aria-live", "polite");
        indicator.setAttribute("aria-atomic", "true");
        indicator.innerHTML =
            'Página <strong data-current-page>1</strong>/<strong data-total-pages>1</strong>';

        controls.appendChild(previousButton);
        controls.appendChild(indicator);
        controls.appendChild(nextButton);

        var pageSize = document.createElement("span");
        pageSize.className = "fp-table-pagination__size";
        pageSize.innerHTML = '<strong data-page-size>' +
            tablePageSize(table) + '</strong> por página';

        pagination.appendChild(summary);
        pagination.appendChild(controls);
        pagination.appendChild(pageSize);
        table.insertAdjacentElement("afterend", pagination);

        var state = {
            currentPage: 1,
            pagination: pagination,
            previousButton: previousButton,
            nextButton: nextButton,
            pageSize: tablePageSize(table)
        };
        paginationStates.set(table, state);

        previousButton.addEventListener("click", function () {
            goToTablePage(table, state.currentPage - 1, true);
        });
        nextButton.addEventListener("click", function () {
            goToTablePage(table, state.currentPage + 1, true);
        });

        return state;
    }

    function resetTableScroll(table) {
        var shell = table.closest(".responsive-table-shell");
        if (!shell || !shell.scrollTo) return;
        shell.scrollTo({ left: 0, behavior: "smooth" });
    }

    function renderTablePagination(table, resetPage) {
        var state = paginationStates.get(table);
        if (!state) return;

        var allRows = tableBodyRows(table);
        allRows.forEach(function (row) {
            row.classList.remove("fp-table-page-hidden");
        });

        var recordRows = allRows.filter(function (row) {
            return row.dataset.paginationSkip !== "true" && !isEmptyStateRow(row);
        });
        var visibleRows = recordRows.filter(function (row) {
            return !isFilteredRow(row);
        });
        var totalRecords = visibleRows.length;
        state.pageSize = tablePageSize(table);
        var totalPages = Math.max(1, Math.ceil(totalRecords / state.pageSize));

        if (resetPage) state.currentPage = 1;
        state.currentPage = Math.min(Math.max(state.currentPage, 1), totalPages);

        var firstIndex = (state.currentPage - 1) * state.pageSize;
        var lastIndex = Math.min(firstIndex + state.pageSize, totalRecords);
        visibleRows.forEach(function (row, index) {
            row.classList.toggle(
                "fp-table-page-hidden",
                index < firstIndex || index >= lastIndex
            );
        });

        var rangeText = totalRecords ? (firstIndex + 1) + "–" + lastIndex : "0";
        state.pagination.querySelector("[data-page-range]").textContent = rangeText;
        state.pagination.querySelector("[data-page-total]").textContent = totalRecords;
        state.pagination.querySelector("[data-current-page]").textContent = state.currentPage;
        state.pagination.querySelector("[data-total-pages]").textContent = totalPages;
        state.pagination.querySelector("[data-page-size]").textContent = state.pageSize;

        state.previousButton.disabled = state.currentPage <= 1;
        state.nextButton.disabled = state.currentPage >= totalPages;
        state.pagination.dataset.totalRecords = String(totalRecords);
        state.pagination.dataset.totalPages = String(totalPages);
    }

    function goToTablePage(table, requestedPage, resetScroll) {
        var state = paginationStates.get(table);
        if (!state) return;
        state.currentPage = requestedPage;
        renderTablePagination(table, false);
        if (resetScroll) resetTableScroll(table);
    }

    function prepareTablePagination(table) {
        if (table.dataset.pagination === "off") return;
        if (!table.tHead || !table.tBodies.length) return;

        if (!paginationStates.has(table)) {
            createTablePagination(table);
            table.dataset.paginationPrepared = "true";
        }
        renderTablePagination(table, false);
    }

    function normalizeTableText(value) {
        var text = String(value || "").toLowerCase().trim();
        if (text.normalize) {
            text = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
        }
        return text.replace(/\s+/g, " ");
    }

    function tableHeaderCells(table) {
        if (!table.tHead || !table.tHead.rows.length) return [];

        return Array.prototype.reduce.call(table.tHead.rows, function (best, row) {
            var cells = Array.prototype.slice.call(row.cells || []);
            return cells.length > best.length ? cells : best;
        }, []);
    }

    function identityColumnIndex(headers) {
        var inlineStickyIndex = headers.findIndex(function (header) {
            return /position\s*:\s*sticky/i.test(header.getAttribute("style") || "");
        });
        if (inlineStickyIndex >= 0) return inlineStickyIndex;

        var normalizedHeaders = headers.map(function (header) {
            return normalizeTableText(header.textContent);
        });
        var identityPatterns = [
            /estudiante|alumno|apellidos? y nombres?|persona|cliente|involucrado/,
            /usuario|asesor|vendedora|registrador/,
            /^nombre\b|\bnombres\b/,
            /^curso\b|curso\s*[\/·]/,
            /concepto|descripcion|detalle|actividad realizada|sede/
        ];

        for (var patternIndex = 0; patternIndex < identityPatterns.length; patternIndex += 1) {
            var matchIndex = normalizedHeaders.findIndex(function (headerText) {
                return identityPatterns[patternIndex].test(headerText);
            });
            if (matchIndex >= 0) return matchIndex;
        }

        var ignoredHeader = /^(#|acciones?|accion|comp\.?|comprob\.?|estado|saldo|pagado|pago|valor|monto|factura|asistencia)$/;
        return normalizedHeaders.findIndex(function (headerText) {
            return headerText && !ignoredHeader.test(headerText);
        });
    }

    function tableContextDescriptors(headers, identityIndex) {
        var descriptorRules = [
            { pattern: /cedula|ruc|documento|identificacion/, label: "C.I./RUC" },
            { pattern: /^curso\b|curso\s*[\/·(]/, label: "Curso" },
            { pattern: /celular|telefono|contacto/, label: "Cel." },
            { pattern: /modalidad/, label: "Modalidad" },
            { pattern: /jornada/, label: "Jornada" },
            { pattern: /^fecha\b|fecha /, label: "Fecha" },
            { pattern: /sede|ciudad/, label: "Sede" }
        ];
        var descriptors = [];

        descriptorRules.some(function (rule) {
            headers.forEach(function (header, index) {
                if (descriptors.length >= 2 || index === identityIndex) return;
                var headerText = normalizeTableText(header.textContent);
                if (!rule.pattern.test(headerText)) return;
                if (descriptors.some(function (descriptor) {
                    return descriptor.index === index;
                })) return;
                descriptors.push({ index: index, label: rule.label });
            });
            return descriptors.length >= 2;
        });

        return descriptors.slice(0, 2);
    }

    function compactCellText(cell) {
        var value = String(cell ? cell.textContent : "").replace(/\s+/g, " ").trim();
        if (!value || value === "—" || value === "-") return "";
        return value.length > 58 ? value.slice(0, 55).trim() + "…" : value;
    }

    function createIdentityContext(row, identityCell, descriptors) {
        if (identityCell.querySelector(".fp-table-identity-context")) return;

        var identityText = normalizeTableText(identityCell.textContent);
        var details = [];
        descriptors.forEach(function (descriptor) {
            var value = compactCellText(row.cells[descriptor.index]);
            if (!value || identityText.indexOf(normalizeTableText(value)) >= 0) return;
            details.push({ label: descriptor.label, value: value });
        });
        if (!details.length) return;

        var context = document.createElement("div");
        context.className = "fp-table-identity-context";
        context.setAttribute("aria-hidden", "true");
        details.forEach(function (detail) {
            var item = document.createElement("span");
            item.className = "fp-table-identity-context__item";

            var label = document.createElement("strong");
            label.textContent = detail.label + ":";
            item.appendChild(label);
            item.appendChild(document.createTextNode(" " + detail.value));
            context.appendChild(item);
        });
        identityCell.appendChild(context);
    }

    function prepareTableIdentity(table) {
        if (!table.tHead || !table.tBodies.length) return;
        if (table.getAttribute("role") === "presentation") return;
        if (table.dataset.tableContext === "off" || table.dataset.tableContext === "custom") return;

        var headers = tableHeaderCells(table);
        if (!headers.length) return;

        var storedIndex = table.dataset.tableIdentityColumn;
        var identityIndex = storedIndex === undefined
            ? identityColumnIndex(headers)
            : Number(storedIndex);
        if (identityIndex < 0 || identityIndex >= headers.length) return;

        table.dataset.tableIdentityColumn = String(identityIndex);
        table.classList.add("fp-table-has-identity");
        headers[identityIndex].classList.add("fp-table-identity-column");

        var descriptors = tableContextDescriptors(headers, identityIndex);
        tableBodyRows(table).forEach(function (row) {
            var identityCell = row.cells[identityIndex];
            if (!identityCell) return;
            identityCell.classList.add("fp-table-identity-column");
            createIdentityContext(row, identityCell, descriptors);
        });
    }

    function prefersReducedMotion() {
        return Boolean(
            window.matchMedia &&
            window.matchMedia("(prefers-reduced-motion: reduce)").matches
        );
    }

    function createTableNavigator(table, shell) {
        if (navigationStates.has(table)) return navigationStates.get(table);

        var navigator = document.createElement("section");
        navigator.className = "fp-table-navigator";
        navigator.setAttribute("aria-label", "Navegación de " + tableLabel(table, 0));

        var toolbar = document.createElement("div");
        toolbar.className = "fp-table-navigator__toolbar";

        var context = document.createElement("div");
        context.className = "fp-table-navigator__context";
        context.innerHTML =
            '<span class="fp-table-navigator__context-icon" aria-hidden="true">↔</span>' +
            '<span><strong>Explora la tabla</strong>' +
            '<small>Desliza la barra o usa el botón para recorrer las columnas.</small></span>';

        var jumpEdge = document.createElement("button");
        jumpEdge.type = "button";
        jumpEdge.className = "fp-table-navigator__jump";
        jumpEdge.setAttribute("aria-label", "Ir al final de la tabla horizontalmente");

        var jumpLabel = document.createElement("span");
        jumpLabel.className = "fp-table-navigator__jump-label";
        jumpLabel.textContent = "Ir al final de la tabla";

        var jumpArrow = document.createElement("span");
        jumpArrow.className = "fp-table-navigator__jump-arrow";
        jumpArrow.setAttribute("aria-hidden", "true");
        jumpArrow.textContent = "→";

        jumpEdge.appendChild(jumpLabel);
        jumpEdge.appendChild(jumpArrow);

        toolbar.appendChild(context);
        toolbar.appendChild(jumpEdge);

        var topScroll = document.createElement("input");
        topScroll.type = "range";
        topScroll.className = "fp-table-navigator__scroll";
        topScroll.min = "0";
        topScroll.max = "0";
        topScroll.step = "1";
        topScroll.value = "0";
        topScroll.setAttribute(
            "aria-label",
            "Barra de desplazamiento horizontal superior de " + tableLabel(table, 0)
        );

        navigator.appendChild(toolbar);
        navigator.appendChild(topScroll);
        shell.parentNode.insertBefore(navigator, shell);

        var state = {
            navigator: navigator,
            shell: shell,
            topScroll: topScroll,
            jumpEdge: jumpEdge,
            jumpLabel: jumpLabel,
            jumpArrow: jumpArrow,
            syncing: false
        };
        navigationStates.set(table, state);

        topScroll.addEventListener("input", function () {
            if (state.syncing) return;
            state.syncing = true;
            shell.scrollLeft = Number(topScroll.value);
            state.syncing = false;
            updateTableNavigator(table);
        });

        shell.addEventListener("scroll", function () {
            if (!state.syncing) {
                state.syncing = true;
                topScroll.value = String(Math.round(shell.scrollLeft));
                state.syncing = false;
            }
            updateTableNavigator(table);
        }, { passive: true });

        jumpEdge.addEventListener("click", function () {
            var maximumScroll = Math.max(0, shell.scrollWidth - shell.clientWidth);
            var isAtEnd = maximumScroll - shell.scrollLeft <= 4;
            var destination = isAtEnd ? 0 : maximumScroll;

            if (shell.scrollTo) {
                shell.scrollTo({
                    left: destination,
                    behavior: prefersReducedMotion() ? "auto" : "smooth"
                });
            } else {
                shell.scrollLeft = destination;
            }
        });

        return state;
    }

    function updateTableNavigator(table) {
        var state = navigationStates.get(table);
        if (!state) return;

        var shell = state.shell;
        var overflowing = shell.scrollWidth > shell.clientWidth + 1;
        var maximumScroll = Math.max(0, shell.scrollWidth - shell.clientWidth);
        var scrollPercentage = maximumScroll
            ? Math.round((shell.scrollLeft / maximumScroll) * 100)
            : 0;
        var isAtEnd = overflowing && maximumScroll - shell.scrollLeft <= 4;

        state.navigator.classList.toggle("is-overflowing", overflowing);
        state.navigator.hidden = !overflowing;
        state.topScroll.hidden = !overflowing;
        state.topScroll.max = String(Math.ceil(maximumScroll));
        state.topScroll.value = String(Math.round(shell.scrollLeft));
        state.topScroll.setAttribute(
            "aria-valuetext",
            scrollPercentage + "% del recorrido horizontal"
        );
        state.jumpLabel.textContent = isAtEnd
            ? "Ir al inicio de la tabla"
            : "Ir al final de la tabla";
        state.jumpArrow.textContent = isAtEnd ? "←" : "→";
        state.jumpEdge.setAttribute(
            "aria-label",
            isAtEnd
                ? "Ir al inicio de la tabla horizontalmente"
                : "Ir al final de la tabla horizontalmente"
        );

        shell.classList.toggle("is-scrolled-x", shell.scrollLeft > 4);
        shell.classList.toggle("is-scrolled-end", isAtEnd);
    }

    function prepareTableNavigator(table, shell) {
        if (table.dataset.tableNavigation === "off") return;
        if (!table.tHead || !table.tBodies.length) return;
        createTableNavigator(table, shell);
        updateTableNavigator(table);
    }

    function refreshTablePaginations(root, resetPage) {
        var scope = root && root.querySelectorAll ? root : document;
        var tables = [];
        if (scope.matches && scope.matches("table")) tables.push(scope);
        scope.querySelectorAll("table").forEach(function (table) {
            tables.push(table);
        });

        tables.forEach(function (table) {
            prepareTablePagination(table);
            if (paginationStates.has(table)) {
                renderTablePagination(table, Boolean(resetPage));
            }
        });
    }

    function prepareResponsiveTables(root) {
        var scope = root && root.querySelectorAll ? root : document;
        var tables = [];

        if (scope.matches && scope.matches("table")) tables.push(scope);
        scope.querySelectorAll("table").forEach(function (table) {
            tables.push(table);
        });

        tables.forEach(function (table, index) {
            if (table.dataset.responsivePrepared === "true") return;

            var shell = table.closest(
                ".table-wrap, .responsive-table-shell, [style*='overflow-x:auto'], [style*='overflow-x: auto']"
            );

            if (!shell) {
                shell = document.createElement("div");
                shell.className = "responsive-table-shell";
                table.parentNode.insertBefore(shell, table);
                shell.appendChild(table);
            } else {
                shell.classList.add("responsive-table-shell");
            }

            if (!shell.dataset.responsiveLabel) {
                shell.dataset.responsiveLabel = tableLabel(table, index);
            }

            table.dataset.responsivePrepared = "true";
            if (resizeObserver) resizeObserver.observe(shell);
            prepareTablePagination(table);
            prepareTableIdentity(table);
            prepareTableNavigator(table, shell);
        });

        scheduleResponsiveTableUpdate();
    }

    function updateResponsiveTables() {
        document.querySelectorAll(".responsive-table-shell").forEach(function (shell) {
            var overflowing = shell.scrollWidth > shell.clientWidth + 1;
            shell.classList.toggle("is-overflowing", overflowing);

            if (overflowing) {
                shell.tabIndex = 0;
                shell.setAttribute("role", "region");
                shell.setAttribute(
                    "aria-label",
                    shell.dataset.responsiveLabel + ". Desliza horizontalmente para ver todas las columnas."
                );
            } else {
                shell.removeAttribute("tabindex");
                shell.removeAttribute("role");
                shell.removeAttribute("aria-label");
            }

            var navigableTable = shell.querySelector(
                'table:not([data-table-navigation="off"])'
            );
            if (navigableTable) updateTableNavigator(navigableTable);
        });
    }

    function scheduleResponsiveTableUpdate() {
        if (updateFrame) return;
        updateFrame = window.requestAnimationFrame(function () {
            updateFrame = 0;
            updateResponsiveTables();
        });
    }

    function watchDynamicTables() {
        if (!("MutationObserver" in window) || !document.body) return;

        var observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    if (node.nodeType === 1) prepareResponsiveTables(node);
                });

                var changedTable = mutation.target.closest
                    ? mutation.target.closest("table")
                    : null;
                if (changedTable) {
                    if (paginationStates.has(changedTable)) {
                        renderTablePagination(changedTable, false);
                    }
                    prepareTableIdentity(changedTable);
                }
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });
    }

    function initResponsiveTables() {
        if ("ResizeObserver" in window) {
            resizeObserver = new ResizeObserver(scheduleResponsiveTableUpdate);
        }
        prepareResponsiveTables(document);
        watchDynamicTables();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initResponsiveTables);
    } else {
        initResponsiveTables();
    }

    window.addEventListener("resize", scheduleResponsiveTableUpdate, { passive: true });
    window.addEventListener("orientationchange", scheduleResponsiveTableUpdate, { passive: true });

    window.FPTablePagination = {
        pageSize: TABLE_PAGE_SIZE,
        refresh: function (root, resetPage) {
            refreshTablePaginations(root || document, Boolean(resetPage));
        },
        goTo: function (table, page) {
            goToTablePage(table, page, false);
        }
    };
})();
