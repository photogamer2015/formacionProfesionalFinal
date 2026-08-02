(function () {
    "use strict";

    var resizeObserver = null;
    var updateFrame = 0;

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
})();
