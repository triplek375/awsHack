const fileSelect = document.querySelector("#fileSelect");
const searchInput = document.querySelector("#searchInput");
const tableHead = document.querySelector("#tableHead");
const tableBody = document.querySelector("#tableBody");
const status = document.querySelector("#status");

const rowCount = document.querySelector("#rowCount");
const columnCount = document.querySelector("#columnCount");
const filenameLabel = document.querySelector("#filename");
const pageInfo = document.querySelector("#pageInfo");
const prevButton = document.querySelector("#prevButton");
const nextButton = document.querySelector("#nextButton");

const pageSize = 50;
let currentPage = 0;
let totalPages = 0;
let requestNumber = 0;

async function loadFiles() {
    try {
        const response = await fetch("/api/csv");

        if (!response.ok) {
            throw new Error("Could not load the file list.");
        }

        const files = await response.json();
        fileSelect.replaceChildren();

        if (files.length === 0) {
            fileSelect.add(new Option("No CSV files found", ""));
            status.textContent = "Add CSV files to the csvFiles folder.";
            return;
        }

        for (const file of files) {
            fileSelect.add(new Option(file.name, file.name));
        }

        await loadPage();
    } catch (error) {
        status.textContent = error.message;
    }
}

async function loadPage() {
    const filename = fileSelect.value;

    if (!filename) return;

    const requestId = ++requestNumber;
    status.textContent = "Loading data...";

    const params = new URLSearchParams({
        page: String(currentPage),
        size: String(pageSize),
        search: searchInput.value.trim()
    });

    try {
        const response = await fetch(
            `/api/csv/${encodeURIComponent(filename)}?${params}`
        );

        if (!response.ok) {
            throw new Error("Could not load this CSV file.");
        }

        const data = await response.json();

        // Ignore an older request if the user selected another file.
        if (requestId !== requestNumber) return;

        renderTable(data);
        status.textContent = data.totalRows === 0
            ? "No matching rows."
            : `Showing ${data.rows.length} rows on this page.`;
    } catch (error) {
        if (requestId !== requestNumber) return;
        status.textContent = error.message;
        tableHead.replaceChildren();
        tableBody.replaceChildren();
    }
}

function renderTable(data) {
    filenameLabel.textContent = data.filename;
    rowCount.textContent = data.totalRows.toLocaleString();
    columnCount.textContent = data.headers.length;
    totalPages = data.totalPages;

    const headerRow = document.createElement("tr");

    for (const header of data.headers) {
        const th = document.createElement("th");
        th.textContent = header;
        headerRow.appendChild(th);
    }

    tableHead.replaceChildren(headerRow);

    const fragment = document.createDocumentFragment();

    for (const row of data.rows) {
        const tr = document.createElement("tr");

        for (let i = 0; i < data.headers.length; i++) {
            const td = document.createElement("td");
            td.textContent = row[i] ?? "";
            tr.appendChild(td);
        }

        fragment.appendChild(tr);
    }

    tableBody.replaceChildren(fragment);

    pageInfo.textContent = totalPages === 0
        ? "Page 0 of 0"
        : `Page ${data.page + 1} of ${totalPages}`;

    prevButton.disabled = data.page <= 0;
    nextButton.disabled =
        totalPages === 0 || data.page >= totalPages - 1;
}

fileSelect.addEventListener("change", () => {
    currentPage = 0;
    searchInput.value = "";
    loadPage();
});

let searchTimer;

searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);

    searchTimer = setTimeout(() => {
        currentPage = 0;
        loadPage();
    }, 250);
});

prevButton.addEventListener("click", () => {
    if (currentPage > 0) {
        currentPage--;
        loadPage();
    }
});

nextButton.addEventListener("click", () => {
    if (currentPage < totalPages - 1) {
        currentPage++;
        loadPage();
    }
});

loadFiles();