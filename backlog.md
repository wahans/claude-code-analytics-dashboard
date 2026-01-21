# Backlog

## High Priority

- [ ] **Functional date filter** - UI exists but doesn't filter data yet; add client-side filtering in JS
- [ ] **Session detail modal** - Replace alert() with proper modal when clicking daily chart bars
- [ ] **Skills analytics** - Track `/skill` invocations from session logs
- [ ] **Hooks analytics** - Parse hook configurations and track executions

## Medium Priority

- [ ] **Heatmap visualization** - Hour-of-day × day-of-week usage heatmap
- [ ] **Line charts for trends** - Add Sparklines or simple SVG line charts for token/cost trends
- [ ] **Comparison mode** - Compare two date ranges side-by-side
- [ ] **Git branch analytics** - Track usage patterns across different branches
- [ ] **Working directory analytics** - Show which directories have most activity
- [ ] **Rules file tracking** - Detect CLAUDE.md references in sessions

## Low Priority

- [ ] **Dark/light theme toggle** - Currently dark-only
- [ ] **Mobile responsiveness** - Improve layout on small screens
- [ ] **Keyboard navigation** - Arrow keys to switch pages, Escape to close modals
- [ ] **Export to PDF** - Generate printable report
- [ ] **Cost budgets/alerts** - Set spending thresholds, highlight when exceeded
- [ ] **Real-time mode** - Watch `~/.claude` for new logs and auto-update

## Ideas (Needs Validation)

- [ ] Bookmark/favorite specific sessions for later review
- [ ] Add notes/annotations to sessions
- [ ] Per-tool cost attribution (estimate cost of Bash vs Read vs Edit)
- [ ] Session "replay" - step through tool calls chronologically
- [ ] Integration with ccusage or other existing tools
- [ ] Shareable dashboard (strip sensitive data, generate public version)
