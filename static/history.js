const chartCanvas = document.getElementById("historyChart");
const statusEl = document.getElementById("historyStatus");
const titleEl = document.getElementById("historyTitle");

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function formatLabel(timestamp) {
  const date = new Date(timestamp);
  return date.toLocaleString();
}

async function loadHistory() {
  const params = new URLSearchParams(window.location.search);
  const symbol = (params.get("symbol") || "").toUpperCase();
  if (!symbol) {
    setStatus("请在 URL 中提供 symbol 参数。", true);
    return;
  }
  titleEl.textContent = `${symbol} 历史数据`;
  setStatus("Loading history…");

  try {
    const url = new URL("/api/history", window.location.origin);
    url.searchParams.set("symbol", symbol);
    url.searchParams.set("limit", "500");
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }
    const payload = await response.json();
    const data = payload.data || [];
    if (data.length === 0) {
      setStatus("暂无历史记录。", true);
      return;
    }

    const labels = data.map((row) => formatLabel(row.timestamp));
    const prices = data.map((row) => row.price);
    const longRatios = data.map((row) =>
      row.longProfitRatio === null || row.longProfitRatio === undefined
        ? null
        : row.longProfitRatio * 100,
    );
    const shortRatios = data.map((row) =>
      row.shortProfitRatio === null || row.shortProfitRatio === undefined
        ? null
        : row.shortProfitRatio * 100,
    );

    const chart = new Chart(chartCanvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Price",
            data: prices,
            borderColor: "#2563eb",
            backgroundColor: "rgba(37, 99, 235, 0.1)",
            yAxisID: "price",
          },
          {
            label: "Long Profit Ratio (%)",
            data: longRatios,
            borderColor: "#16a34a",
            backgroundColor: "rgba(22, 163, 74, 0.1)",
            yAxisID: "ratio",
          },
          {
            label: "Short Profit Ratio (%)",
            data: shortRatios,
            borderColor: "#f97316",
            backgroundColor: "rgba(249, 115, 22, 0.1)",
            yAxisID: "ratio",
          },
        ],
      },
      options: {
        responsive: true,
        interaction: {
          mode: "index",
          intersect: false,
        },
        scales: {
          price: {
            type: "linear",
            position: "left",
            title: {
              display: true,
              text: "Price",
            },
          },
          ratio: {
            type: "linear",
            position: "right",
            title: {
              display: true,
              text: "Profit Ratio (%)",
            },
            grid: {
              drawOnChartArea: false,
            },
          },
        },
      },
    });

    chartCanvas.dataset.ready = "true";
    setStatus(`已加载 ${data.length} 条记录。`);
  } catch (error) {
    console.error(error);
    setStatus("无法加载历史记录。", true);
  }
}

loadHistory();
