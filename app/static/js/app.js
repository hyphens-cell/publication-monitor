(() => {
    "use strict";

    const COLORS = {
        primary: "#5314CD",
        accent: "#14CCAE",
        grid: "rgba(0, 0, 0, 0.06)"
    };

    const clampProgress = (value) => {
        const number = Number(value);

        if (!Number.isFinite(number)) {
            return 0;
        }

        return Math.min(Math.max(number, 0), 100);
    };

    const readAnalyticsData = () => {
        const element = document.getElementById("analytics-data");

        if (!element) {
            return null;
        }

        try {
            return JSON.parse(element.textContent || "{}");
        } catch (error) {
            console.error("Ошибка данных аналитики:", error);
            return null;
        }
    };

    const initializeProgressBars = () => {
        document.querySelectorAll("[data-progress]").forEach((element) => {
            element.style.width = `${clampProgress(element.dataset.progress)}%`;
        });
    };

    const createChartOptions = () => ({
        responsive: true,
        maintainAspectRatio: false
    });

    const initializePlanFactChart = (data) => {
        const canvas = document.getElementById("analyticsPlanFactChart");

        if (!canvas || typeof Chart === "undefined") {
            return;
        }

        new Chart(canvas, {
            type: "bar",
            data: {
                labels: ["План", "Факт"],
                datasets: [{
                    label: "Количество",
                    data: [
                        Number(data.summary?.planned || 0),
                        Number(data.summary?.actual || 0)
                    ],
                    backgroundColor: [COLORS.primary, COLORS.accent],
                    borderRadius: 8,
                    borderSkipped: false
                }]
            },
            options: {
                ...createChartOptions(),
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            precision: 0
                        },
                        grid: {
                            color: COLORS.grid
                        }
                    },
                    x: {
                        grid: {
                            display: false
                        }
                    }
                }
            }
        });
    };

    const initializeDepartmentChart = (data) => {
        const canvas = document.getElementById(
            "analyticsDepartmentProgressChart"
        );
        const departments = Array.isArray(data.departments)
            ? data.departments
            : [];

        if (!canvas || !departments.length || typeof Chart === "undefined") {
            return;
        }

        new Chart(canvas, {
            type: "bar",
            data: {
                labels: departments.map(
                    (item) => item.name || "Без названия"
                ),
                datasets: [
                    {
                        label: "План",
                        data: departments.map(
                            (item) => Number(item.planned_count || 0)
                        ),
                        backgroundColor: COLORS.primary,
                        borderRadius: 7,
                        borderSkipped: false
                    },
                    {
                        label: "Факт",
                        data: departments.map(
                            (item) => Number(item.actual_count || 0)
                        ),
                        backgroundColor: COLORS.accent,
                        borderRadius: 7,
                        borderSkipped: false
                    }
                ]
            },
            options: {
                ...createChartOptions(),
                indexAxis: "y",
                plugins: {
                    legend: {
                        position: "bottom"
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: {
                            precision: 0
                        },
                        grid: {
                            color: COLORS.grid
                        }
                    },
                    y: {
                        grid: {
                            display: false
                        }
                    }
                }
            }
        });
    };

    const getPublicationTypeLabel = (item, language) => {
        if (language === "kk") {
            return item.name_kk || item.name_ru || "Без названия";
        }

        return item.name_ru || item.name_kk || "Без названия";
    };

    const initializePublicationTypeChart = (data) => {
        const canvas = document.getElementById(
            "analyticsPublicationTypeChart"
        );
        const publicationTypes = Array.isArray(data.publicationTypes)
            ? data.publicationTypes
            : [];

        if (
            !canvas ||
            !publicationTypes.length ||
            typeof Chart === "undefined"
        ) {
            return;
        }

        new Chart(canvas, {
            type: "bar",
            data: {
                labels: publicationTypes.map(
                    (item) => getPublicationTypeLabel(item, data.language)
                ),
                datasets: [
                    {
                        label: "План",
                        data: publicationTypes.map(
                            (item) => Number(item.planned_count || 0)
                        ),
                        backgroundColor: COLORS.primary,
                        borderRadius: 7,
                        borderSkipped: false
                    },
                    {
                        label: "Факт",
                        data: publicationTypes.map(
                            (item) => Number(item.actual_count || 0)
                        ),
                        backgroundColor: COLORS.accent,
                        borderRadius: 7,
                        borderSkipped: false
                    }
                ]
            },
            options: {
                ...createChartOptions(),
                plugins: {
                    legend: {
                        position: "bottom"
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            precision: 0
                        },
                        grid: {
                            color: COLORS.grid
                        }
                    },
                    x: {
                        grid: {
                            display: false
                        }
                    }
                }
            }
        });
    };

    const initializeAnalytics = () => {
        const data = readAnalyticsData();

        if (!data) {
            return;
        }

        initializeProgressBars();

        if (typeof Chart === "undefined") {
            console.error(
                "Chart.js не загружен. Подключите его перед app.js."
            );
            return;
        }

        initializePlanFactChart(data);
        initializeDepartmentChart(data);
        initializePublicationTypeChart(data);
    };


    const initializeDropdownPortals = () => {
        document.addEventListener(
            "shown.bs.dropdown",
            (event) => {
                const button = event.target;

                if (!(button instanceof HTMLElement)) {
                    return;
                }

                const dropdown = button.closest(".dropdown");

                if (!dropdown) {
                    return;
                }

                const menu = dropdown.querySelector(
                    ":scope > .dropdown-menu"
                );

                if (!menu || menu.classList.contains("pm-dropdown-portal")) {
                    return;
                }

                const rect = button.getBoundingClientRect();

                menu._pmOriginalParent = dropdown;
                menu._pmOriginalClassName = menu.className;
                menu._pmOriginalStyle = menu.getAttribute("style");

                document.body.appendChild(menu);
                menu.classList.add("pm-dropdown-portal");

                const isMobile = window.innerWidth <= 767.98;

                if (isMobile) {
                    menu.style.left = "12px";
                    menu.style.right = "12px";
                    menu.style.top = `${rect.bottom + 6}px`;
                    menu.style.width = `${window.innerWidth - 24}px`;
                } else {
                    menu.style.left = `${Math.max(
                        8,
                        rect.right - menu.offsetWidth
                    )}px`;
                    menu.style.top = `${rect.bottom + 6}px`;
                }
            }
        );

        document.addEventListener(
            "hidden.bs.dropdown",
            (event) => {
                const button = event.target;

                if (!(button instanceof HTMLElement)) {
                    return;
                }

                const menu = document.querySelector(
                    ".pm-dropdown-portal"
                );

                if (!menu || !menu._pmOriginalParent) {
                    return;
                }

                menu._pmOriginalParent.appendChild(menu);

                menu.className =
                    menu._pmOriginalClassName || "dropdown-menu";

                if (menu._pmOriginalStyle) {
                    menu.setAttribute(
                        "style",
                        menu._pmOriginalStyle
                    );
                } else {
                    menu.removeAttribute("style");
                }

                delete menu._pmOriginalParent;
                delete menu._pmOriginalClassName;
                delete menu._pmOriginalStyle;
            }
        );

        const repositionDropdown = () => {
            const menu = document.querySelector(
                ".pm-dropdown-portal"
            );

            if (!menu || !menu._pmOriginalParent) {
                return;
            }

            const button = menu._pmOriginalParent.querySelector(
                '[data-bs-toggle="dropdown"]'
            );

            if (!button) {
                return;
            }

            const rect = button.getBoundingClientRect();
            const isMobile = window.innerWidth <= 767.98;

            menu.style.top = `${rect.bottom + 6}px`;

            if (isMobile) {
                menu.style.left = "12px";
                menu.style.right = "12px";
                menu.style.width = `${window.innerWidth - 24}px`;
            } else {
                menu.style.right = "auto";
                menu.style.width = "auto";
                menu.style.left = `${Math.max(
                    8,
                    rect.right - menu.offsetWidth
                )}px`;
            }
        };

        window.addEventListener(
            "resize",
            repositionDropdown
        );

        window.addEventListener(
            "scroll",
            repositionDropdown,
            { passive: true }
        );
    };

    const initializeDestructiveActionConfirmation = () => {
        const destructivePattern = /\/(delete|archive|block)(?:\/|$)/;

        document.querySelectorAll("form[action]").forEach((form) => {
            if (!destructivePattern.test(form.action)) {
                return;
            }

            form.addEventListener("submit", (event) => {
                if (!window.confirm(window.pmMessages?.confirmDestructive || "Confirm destructive action.")) {
                    event.preventDefault();
                }
            });
        });
    };

    const initializeSubmitStates = () => {
        document.querySelectorAll("form").forEach((form) => {
            form.addEventListener("submit", (event) => {
                if (event.defaultPrevented) {
                    return;
                }
                const submitters = form.querySelectorAll(
                    'button[type="submit"], input[type="submit"]'
                );
                form.setAttribute("aria-busy", "true");
                form.classList.add("is-submitting");
                submitters.forEach((control) => {
                    control.disabled = true;
                    control.setAttribute("aria-disabled", "true");
                });
            });
        });
    };

    const initializeResponsiveTables = () => {
        document.querySelectorAll(".table-responsive table").forEach((table) => {
            const headers = Array.from(table.querySelectorAll("thead th")).map(
                (header) => header.textContent.trim()
            );

            if (!headers.length) {
                return;
            }

            table.classList.add("pm-responsive-table");
            table.querySelectorAll("tbody tr").forEach((row) => {
                Array.from(row.children).forEach((cell, index) => {
                    if (cell.hasAttribute("colspan")) {
                        cell.classList.add("pm-table-empty-cell");
                        return;
                    }
                    cell.dataset.label = headers[index] || "";
                });
            });
        });
    };

    const initializeApplication = () => {
        initializeAnalytics();
        initializeDropdownPortals();
        initializeDestructiveActionConfirmation();
        initializeSubmitStates();
        initializeResponsiveTables();
    };

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            initializeApplication,
            { once: true }
        );
    } else {
        initializeApplication();
    }
})();
