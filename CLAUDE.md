# Claude Code Analytics Dashboard

## Project Overview
Single-file HTML dashboard that visualizes Claude Code usage by parsing `~/.claude` folder logs. Generates a standalone HTML file with embedded data - no server required.

## Architecture

```
generate_dashboard.py  → Parses JSONL logs, extracts metrics, injects into template
template.html          → Dashboard UI with __DATA_PLACEHOLDER__ for injection
my-dashboard.html      → Generated output (gitignored, contains personal data)
```

**Data flow:** JSONL files → Python extractor → JSON blob → injected into template → standalone HTML

## Key Files

| File | Purpose |
|------|---------|
| `generate_dashboard.py` | Data extraction, aggregation, cost calculation, insight generation |
| `template.html` | Dashboard UI - vanilla HTML/CSS/JS, no build step, no dependencies |

## Conventions

### Python (generate_dashboard.py)
- Single file, no external dependencies beyond stdlib
- `extract_analytics()` returns full data dict
- Pricing constants at top: `PRICING = {'sonnet': {...}, 'opus': {...}, 'haiku': {...}}`
- Session data accumulated in `all_sessions` list
- Cost calculated via `calc_cost(tokens, model)` helper

### Template (template.html)
- Vanilla JS, no frameworks
- Dark theme matching GitHub's dark mode
- `DATA` global contains injected analytics
- `render*()` functions populate each page
- Navigation via `data-page` attributes on `.nav-item` elements
- Charts are simple div-based bars, no charting library

### CSS Classes
- `.card` - stat cards with `.card-value.blue|green|yellow|purple`
- `.chart-box` - containers for charts/tables
- `.badge` - labels with `.badge-blue|green|purple|yellow`
- `.expandable` / `.expand-content` - collapsible table rows
- `.health-item` - config health check items

## Adding Features

### New metric in Python:
1. Add tracking in session loop
2. Aggregate after loop
3. Add to return dict

### New page in template:
1. Add nav item: `<div class="nav-item" data-page="newpage">...</div>`
2. Add page div: `<div id="page-newpage" class="page hidden">...</div>`
3. Add render function: `function renderNewPage() {...}`
4. Call in `init()`

## Testing
```bash
python3 generate_dashboard.py
open my-dashboard.html
```

No test suite - manual verification by regenerating and checking the dashboard.

## Gotchas
- `my-dashboard.html` contains personal usage data - never commit
- Template uses `__DATA_PLACEHOLDER__` literal - don't change this string
- JSONL parsing must handle malformed entries gracefully
- Cost calculations assume Claude API pricing (may need updates)
