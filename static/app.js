const tableBody = document.getElementById("tableBody");
const statusEl = document.getElementById("status");
const perPageSelect = document.getElementById("perPage");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const pageInfo = document.getElementById("pageInfo");

let currentPage = 1;
let totalPages = 1;
let sortKey = "symbol";
let sortOrder = "asc";
let useMockData = new URLSearchParams(window.location.search).get("mock") === "1";

function formatRatio(value) {
  if (value === null || value === undefined) {
    return "N/A";
  }
  return `${(value * 100).toFixed(2)}%`;
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function renderTable(rows) {
  tableBody.innerHTML = "";
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.symbol}</td>
      <td>${formatRatio(row.longProfitRatio)}</td>
      <td>${formatRatio(row.shortProfitRatio)}</td>
    `;
    tableBody.appendChild(tr);
  });
}

async function fetchData() {
  const perPage = Number(perPageSelect.value);
  const endpoint = useMockData ? "/static/mock-data.json" : "/api/profit-ratios";
  const url = new URL(endpoint, window.location.origin);

  if (!useMockData) {
    url.searchParams.set("page", currentPage);
    url.searchParams.set("per_page", perPage);
    url.searchParams.set("sort", sortKey);
    url.searchParams.set("order", sortOrder);
  }

  setStatus("Loading data…");

  try {
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }
    const payload = await response.json();
    if (useMockData) {
      renderTable(payload.data);
      totalPages = 1;
      pageInfo.textContent = "Mock data";
    } else {
      renderTable(payload.data);
      totalPages = payload.totalPages || 1;
      pageInfo.textContent = `Page ${payload.page} of ${totalPages}`;
    }
    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = currentPage >= totalPages;
    setStatus("Data loaded.");
  } catch (error) {
    console.error(error);
    setStatus("Unable to load live data. Showing mock data instead.", true);
    useMockData = true;
    currentPage = 1;
    await fetchData();
  }
}

function updateSort(newKey) {
  if (sortKey === newKey) {
    sortOrder = sortOrder === "asc" ? "desc" : "asc";
  } else {
    sortKey = newKey;
    sortOrder = "asc";
  }
  fetchData();
}

function initSorting() {
  document.querySelectorAll("th[data-sort]").forEach((header) => {
    header.addEventListener("click", () => updateSort(header.dataset.sort));
  });
}

prevBtn.addEventListener("click", () => {
  if (currentPage > 1) {
    currentPage -= 1;
    fetchData();
  }
});

nextBtn.addEventListener("click", () => {
  if (currentPage < totalPages) {
    currentPage += 1;
    fetchData();
  }
});

perPageSelect.addEventListener("change", () => {
  currentPage = 1;
  fetchData();
});

initSorting();
fetchData();
