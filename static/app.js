const tableBody = document.getElementById("tableBody");
const statusEl = document.getElementById("status");
const perPageSelect = document.getElementById("perPage");
const refreshIntervalInput = document.getElementById("refreshInterval");
const warningThresholdInput = document.getElementById("warningThreshold");
const longWarningSoundInput = document.getElementById("longWarningSound");
const shortWarningSoundInput = document.getElementById("shortWarningSound");
const warningVolumeInput = document.getElementById("warningVolume");
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
const lastRowRefresh = new Map();
const lastWarningSound = new Map();
const warningSoundCooldownMs = 5000;
let audioContext = null;

function formatRatio(value) {
  if (value === null || value === undefined) {
    return "N/A";
  }
  return `${(value * 100).toFixed(2)}%`;
}

function formatPrice(value) {
  if (value === null || value === undefined) {
    return "N/A";
  }
  const numberValue = Number(value);
  if (Number.isNaN(numberValue)) {
    return "N/A";
  }
  return numberValue.toLocaleString(undefined, { maximumFractionDigits: 8 });
}

function getWarningThreshold() {
  const threshold = Number(warningThresholdInput.value);
  if (Number.isNaN(threshold) || threshold < 0) {
    return 1.5;
  }
  return threshold;
}

function getWarningVolume() {
  const volume = Number(warningVolumeInput.value);
  if (Number.isNaN(volume)) {
    return 0.08;
  }
  return Math.min(Math.max(volume, 0), 1);
}

function playWarningSound() {
  try {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContext.state === "suspended") {
      audioContext.resume();
    }
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = 880;
    gainNode.gain.value = getWarningVolume();
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + 0.18);
  } catch (error) {
    console.warn("Audio warning not available.", error);
  }
}

function maybePlayWarningSound(type, symbol) {
  const enabled =
    (type === "long" && longWarningSoundInput.checked) ||
    (type === "short" && shortWarningSoundInput.checked);
  if (!enabled) {
    return;
  }
  const key = `${type}:${symbol}`;
  const lastPlayed = lastWarningSound.get(key);
  const now = Date.now();
  if (lastPlayed && now - lastPlayed < warningSoundCooldownMs) {
    return;
  }
  lastWarningSound.set(key, now);
  playWarningSound();
}

function applyWarningState(tr, cell, value, type) {
  const hasValue = value !== null && value !== undefined;
  const threshold = getWarningThreshold();
  const isWarning = hasValue && value * 100 < threshold;
  if (cell) {
    cell.classList.toggle("ratio-warning", isWarning);
  }
  const dataKey = type === "long" ? "warnLong" : "warnShort";
  const prevWarning = tr.dataset[dataKey] === "true";
  tr.dataset[dataKey] = String(isWarning);
  if (isWarning && !prevWarning) {
    maybePlayWarningSound(type, tr.dataset.symbol || "");
  }
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
    tr.dataset.long = row.longProfitRatio ?? "";
    tr.dataset.short = row.shortProfitRatio ?? "";
    tr.innerHTML = `
      <td><a href="/history?symbol=${row.symbol}">${row.symbol}</a></td>
      <td>${formatPrice(row.price)}</td>
      <td>${formatRatio(row.longProfitRatio)}</td>
      <td>${formatRatio(row.shortProfitRatio)}</td>
      <td><button class="row-refresh" type="button" data-symbol="${row.symbol}">刷新</button></td>
    `;
    const cells = tr.querySelectorAll("td");
    applyWarningState(tr, cells[2], row.longProfitRatio, "long");
    applyWarningState(tr, cells[3], row.shortProfitRatio, "short");
    tableBody.appendChild(tr);
  });
}

function updateRow(tr, payload) {
  const cells = tr.querySelectorAll("td");
  if (cells.length < 4) {
    return;
  }
  tr.dataset.long = payload.longProfitRatio ?? "";
  tr.dataset.short = payload.shortProfitRatio ?? "";
  cells[1].textContent = formatPrice(payload.price);
  cells[2].textContent = formatRatio(payload.longProfitRatio);
  cells[3].textContent = formatRatio(payload.shortProfitRatio);
  applyWarningState(tr, cells[2], payload.longProfitRatio, "long");
  applyWarningState(tr, cells[3], payload.shortProfitRatio, "short");
}

function updateWarningStyles() {
  tableBody.querySelectorAll("tr").forEach((row) => {
    const cells = row.querySelectorAll("td");
    if (cells.length < 4) {
      return;
    }
    const longValue = row.dataset.long === "" ? null : Number(row.dataset.long);
    const shortValue = row.dataset.short === "" ? null : Number(row.dataset.short);
    applyWarningState(row, cells[2], Number.isNaN(longValue) ? null : longValue, "long");
    applyWarningState(row, cells[3], Number.isNaN(shortValue) ? null : shortValue, "short");
  });
}

async function refreshSymbolRow(button) {
  const symbol = button.dataset.symbol;
  if (!symbol) {
    return;
  }
  const lastRefresh = lastRowRefresh.get(symbol);
  if (lastRefresh && Date.now() - lastRefresh < 3000) {
    setStatus(`请稍候再刷新 ${symbol}。`, true);
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
    if (payload.stale) {
      setStatus(`${symbol} 刷新失败，已使用缓存数据。`, true);
    } else {
      setStatus(`已刷新 ${symbol}。`);
    }
    lastRowRefresh.set(symbol, Date.now());
  } catch (error) {
    console.error(error);
    setStatus(`无法刷新 ${symbol}。`, true);
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function fetchData({
  forceRefresh = false,
  allowMockFallback = false,
  tryLiveWhenMocked = false,
} = {}) {
  const perPage = Number(perPageSelect.value);
  const shouldTryLive = !useMockData || (useMockData && tryLiveWhenMocked);
  const endpoint = shouldTryLive ? "/api/profit-ratios" : "/static/mock-data.json";
  const url = new URL(endpoint, window.location.origin);

  if (shouldTryLive) {
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
    if (!shouldTryLive) {
      renderTable(payload.data);
      totalPages = 1;
      pageInfo.textContent = "Mock data";
    } else {
      renderTable(payload.data);
      useMockData = false;
      totalPages = payload.totalPages || 1;
      pageInfo.textContent = `Page ${payload.page} of ${totalPages}`;
    }
    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = currentPage >= totalPages;
    setStatus("Data loaded.");
  } catch (error) {
    console.error(error);
    if (!shouldTryLive) {
      setStatus("Unable to load mock data.", true);
      return;
    }
    if (allowMockFallback) {
      setStatus("Unable to load live data. Showing mock data instead.", true);
      useMockData = true;
      currentPage = 1;
      await fetchData({ allowMockFallback: false });
      return;
    }
    setStatus("无法获取最新数据，请稍后重试。", true);
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
  fetchData({ forceRefresh: true, tryLiveWhenMocked: true });
});

function setRefreshTimer() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
  const seconds = Number(refreshIntervalInput.value);
  if (!Number.isNaN(seconds) && seconds > 0) {
    refreshTimer = setInterval(() => {
      fetchData({ forceRefresh: true, tryLiveWhenMocked: true });
    }, seconds * 1000);
    autoRefreshStatus.textContent = `自动刷新：每 ${seconds} 秒`;
  } else {
    autoRefreshStatus.textContent = "自动刷新：未启用";
  }
}

refreshIntervalInput.addEventListener("input", setRefreshTimer);
warningThresholdInput.addEventListener("input", updateWarningStyles);
warningVolumeInput.addEventListener("change", playWarningSound);

initSorting();
fetchData({ allowMockFallback: true, tryLiveWhenMocked: true });
setRefreshTimer();
updateWarningStyles();
