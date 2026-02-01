const tableBody = document.getElementById("tableBody");
const statusEl = document.getElementById("status");
const perPageSelect = document.getElementById("perPage");
const refreshIntervalInput = document.getElementById("refreshInterval");
const refreshBtn = document.getElementById("refreshBtn");
const autoRefreshStatus = document.getElementById("autoRefreshStatus");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const pageInfo = document.getElementById("pageInfo");

let currentPage = 1;
let totalPages = 1;
let sortKey = "symbol";
let sortOrder = "asc";
let useMockData = new URLSearchParams(window.location.search).get("mock") === "1";
let refreshTimer = null;

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
    tr.dataset.symbol = row.symbol;
    tr.innerHTML = `
      <td>${row.symbol}</td>
      <td>${formatRatio(row.longProfitRatio)}</td>
      <td>${formatRatio(row.shortProfitRatio)}</td>
      <td><button class="row-refresh" type="button" data-symbol="${row.symbol}">刷新</button></td>
    `;
    tableBody.appendChild(tr);
  });
}

function updateRow(tr, payload) {
  const cells = tr.querySelectorAll("td");
  if (cells.length < 3) {
    return;
  }
  cells[1].textContent = formatRatio(payload.longProfitRatio);
  cells[2].textContent = formatRatio(payload.shortProfitRatio);
}

async function refreshSymbolRow(button) {
  const symbol = button.dataset.symbol;
  if (!symbol) {
    return;
  }
  if (useMockData) {
    setStatus("Mock 数据模式无法单独刷新，请切换到实时数据。", true);
    return;
  }
  const row = button.closest("tr");
  if (!row) {
    return;
  }
  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "刷新中…";
  try {
    const url = new URL("/api/profit-ratio", window.location.origin);
    url.searchParams.set("symbol", symbol);
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }
    const payload = await response.json();
    updateRow(row, payload);
    setStatus(`已刷新 ${symbol}。`);
  } catch (error) {
    console.error(error);
    setStatus(`无法刷新 ${symbol}。`, true);
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function fetchData({ forceRefresh = false } = {}) {
  const perPage = Number(perPageSelect.value);
  const endpoint = useMockData ? "/static/mock-data.json" : "/api/profit-ratios";
  const url = new URL(endpoint, window.location.origin);

  if (!useMockData) {
    url.searchParams.set("page", currentPage);
    url.searchParams.set("per_page", perPage);
    url.searchParams.set("sort", sortKey);
    url.searchParams.set("order", sortOrder);
    if (forceRefresh) {
      url.searchParams.set("refresh", "1");
    }
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

tableBody.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  if (target.matches(".row-refresh")) {
    refreshSymbolRow(target);
  }
});

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

refreshBtn.addEventListener("click", () => {
  fetchData({ forceRefresh: true });
});

function setRefreshTimer() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
  const seconds = Number(refreshIntervalInput.value);
  if (!Number.isNaN(seconds) && seconds > 0) {
    refreshTimer = setInterval(() => {
      fetchData({ forceRefresh: true });
    }, seconds * 1000);
    autoRefreshStatus.textContent = `自动刷新：每 ${seconds} 秒`;
  } else {
    autoRefreshStatus.textContent = "自动刷新：未启用";
  }
}

refreshIntervalInput.addEventListener("input", setRefreshTimer);

initSorting();
fetchData();
setRefreshTimer();
