# Period Selection CSV Export

Standard pattern for adding period-based (Single Week or Range Week) CSV exports to OKR/SOW dashboard subpages.

## User Interface: Period Selection Modal

- **Rule**: Use a standardized overlay modal (`exportCsvModal`) for CSV exports that require period selection. This avoids cluttering the main filter card with range-selection UI that is only needed during export.
- **Trigger**: The main "Export CSV" button should call `openExportCsvModal(target_id)`.
- **Modal Logic**:
  - Provide a toggle (radio or select) between "Single Week" and "Range Week".
  - Populate week selectors from the page's primary week filter dropdowns (e.g., `filterWeek`, `filterStartYw`) on open.
  - Default to "Single Week" with the latest available week selected.
  - Use `window.location.href = url` to trigger the browser's download prompt for the CSV response.

## JavaScript URL Construction

- **Pitfall**: The `exportTarget` passed to `openExportCsvModal()` is interpolated into URL construction:
  ```javascript
  let url = `/api/sow/${exportTarget}-csv-export?`
  ```
  The target ID must match the Blueprint route decorator **exactly**, including dashes vs underscores. For example:
  - `openExportCsvModal('crowdsource_onx')` → `/api/sow/crowdsource_onx-csv-export`
  - `openExportCsvModal('rhi')` → `/api/sow/rhi-csv-export`
  - `openExportCsvModal('ran_capacity')` → `/api/sow/ran_capacity-csv-export`

- **Rule**: Use underscores (snake_case) in target IDs for consistency with Python naming conventions. Update route decorators to match: `@sow.route('/api/sow/<target>-csv-export', ...)`

## Backend: Flask Route Pattern

- **Route Structure**: `/api/sow/<target>-csv-export`
- **Query Parameters**:
  - `week`: Used for single week export.
  - `start_week` / `end_week`: Used for range export.
  - `region`: (Optional) Filter by region if the table is multi-regional.
- **Implementation Steps**:
  1. Parse week parameters as integers. If `start_week` > `end_week`, swap them to handle user selection errors gracefully.
  2. Query the source table (e.g., `sow.cei_score`, `sow.rhi_score`, `sow.onx_rank_score`) using the range.
  3. Generate CSV in-memory using `io.StringIO` (or `io.BytesIO` with utf-8 encoding).
  4. Use `flask.send_file` with `mimetype="text/csv"` and `as_attachment=True`.
  5. **Pitfall**: Forgetting `charset=utf-8` or encoding in `send_file` can lead to corrupt files or broken characters in Excel. Always encode the CSV buffer as `utf-8`.

## Component Cleanliness

- **Rule**: When adding the modal to a page, place the HTML and `<script>` block at the very end of the file, just before `{% endblock %}`.
- **Pitfall**: Adding the modal multiple times (via failed patches or duplication) can lead to JS conflicts where the `id` lookup finds the wrong instance. Grep the file for `exportCsvModal` after patching to ensure only one instance exists.
- **Pitfall**: Using inline `<a href="...">` links instead of modal-based exports bypasses proper URL construction. Replace direct links with buttons calling `openExportCsvModal(target)`.
- **Pitfall**: Duplicate `@sow.route` decorators on the same endpoint function cause `AssertionError: View function mapping is overwriting an existing endpoint function`. Ensure each route function has exactly one decorator.
- **Standard Filename Pattern**: `[KPI_Name]_OKR_Export_[StartYW]-[EndYW].csv`.