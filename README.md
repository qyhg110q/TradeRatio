# Binance Smart Money Profit Ratios

This project fetches Binance futures Smart Money signal data, calculates long/short profit ratios for all active futures trading pairs, and displays them in a sortable, paginated table.

## Features

- **Backend API**: `/api/profit-ratios` returns long/short profit ratios for all active futures symbols.
- **Frontend UI**: Responsive table with sorting and pagination.
- **Mock Data Mode**: Add `?mock=1` to the URL to load sample data (or use it automatically when live data fails).
- **Tests**: Validates ratio calculations and mock frontend data schema.

## Requirements

- Python 3.10+

Install dependencies:

```bash
pip install -r requirements.txt
```

## Running the Backend

```bash
python app.py
```

The Flask app will be available at `http://localhost:5000`.

## API Reference

`GET /api/profit-ratios`

Query parameters:

- `page` (default: 1)
- `per_page` (default: 50, max: 200)
- `sort` (`symbol`, `long`, or `short`)
- `order` (`asc` or `desc`)

Response example:

```json
{
  "page": 1,
  "perPage": 50,
  "total": 450,
  "totalPages": 9,
  "sort": "long",
  "order": "desc",
  "data": [
    {
      "symbol": "MONUSDT",
      "longProfitRatio": 0.2419,
      "shortProfitRatio": 0.8407
    }
  ]
}
```

## Frontend Usage

- Open `http://localhost:5000` to view the table.
- Click any column header to sort.
- Use **Rows per page** to adjust pagination.
- Add `?mock=1` to the URL to load mock data from `static/mock-data.json`.

## Testing

Run the tests with:

```bash
pytest
```
