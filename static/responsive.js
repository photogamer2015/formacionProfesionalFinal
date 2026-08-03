(function () {
    "use strict";

    var TABLE_PAGE_SIZE = 5;
    var resizeObserver = null;
    var updateFrame = 0;
    var paginationSequence = 0;
    var paginationStates = new WeakMap();

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
        pageSize.textContent = TABLE_PAGE_SIZE + " por página";

        pagination.appendChild(summary);
        pagination.appendChild(controls);
        pagination.appendChild(pageSize);
        table.insertAdjacentElement("afterend", pagination);

        var state = {
            currentPage: 1,
            pagination: pagination,
            previousButton: previousButton,
            nextButton: nextButton
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
        var totalPages = Math.max(1, Math.ceil(totalRecords / TABLE_PAGE_SIZE));

        if (resetPage) state.currentPage = 1;
        state.currentPage = Math.min(Math.max(state.currentPage, 1), totalPages);

        var firstIndex = (state.currentPage - 1) * TABLE_PAGE_SIZE;
        var lastIndex = Math.min(firstIndex + TABLE_PAGE_SIZE, totalRecords);
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
                ".table-wrap, .responsive-table-shell, .dashboard-modal-body, [style*='overflow-x:auto'], [style*='overflow-x: auto']"
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
                if (changedTable && paginationStates.has(changedTable)) {
                    renderTablePagination(changedTable, false);
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
