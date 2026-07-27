(function () {
    "use strict";

    function prepareResponsiveTables() {
        var tables = document.querySelectorAll("table");

        tables.forEach(function (table, index) {
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
                shell.dataset.responsiveLabel = "Tabla " + (index + 1);
            }
        });

        updateResponsiveTables();
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

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", prepareResponsiveTables);
    } else {
        prepareResponsiveTables();
    }

    window.addEventListener("resize", updateResponsiveTables, { passive: true });
    window.addEventListener("orientationchange", updateResponsiveTables, { passive: true });
})();
