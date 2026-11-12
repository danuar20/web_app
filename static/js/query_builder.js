/* NetKPI Query Database — visual Query Builder.
 *
 * Builds a single-table SELECT against the public schema and transfers it to
 * the existing #qdbSql editor. Nothing is executed from this dialog: "Build"
 * fills the editor, "Build and Run" additionally clicks the console's own Run
 * button, so every backend guard (validation, timeouts, row caps) still runs.
 *
 * No dependencies. Metadata comes from /api/query_db/tables and
 * /api/query_db/columns?table=...
 */
(function () {
    "use strict";

    var AGGREGATES = ["NONE", "SUM", "AVG", "MIN", "MAX", "COUNT"];
    var OPERATORS = ["=", "!=", ">", ">=", "<", "<=", "ILIKE", "IS NULL", "IS NOT NULL"];
    var HAVING_OPERATORS = ["=", "!=", ">", ">=", "<", "<="];
    var NULL_OPS = { "IS NULL": true, "IS NOT NULL": true };
    var DEFAULT_LIMIT = 100;
    var MAX_LIMIT = 1000;

    var state = {
        tables: [],
        tablesLoaded: false,
        table: "",
        columns: [],
        loadingColumns: false,
        output: {},
        where: [],
        groupBy: [],
        orderBy: [],
        having: [],
        distinct: false,
        limit: DEFAULT_LIMIT
    };

    var cache = {};
    var el = {};
    var lastFocus = null;
    var pendingFocus = null;
    var pendingRun = false;

    // ── Small helpers ──────────────────────────────────────────────────────
    function esc(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function quoteIdent(name) {
        return '"' + String(name == null ? "" : name).replace(/"/g, '""') + '"';
    }

    function quoteLiteral(value) {
        // Standard-conforming literal: double single quotes, drop NUL bytes.
        return "'" + String(value == null ? "" : value).replace(/\u0000/g, "").replace(/'/g, "''") + "'";
    }

    function columnInfo(name) {
        for (var i = 0; i < state.columns.length; i += 1) {
            if (state.columns[i].name === name) return state.columns[i];
        }
        return null;
    }

    function isNumericType(type) {
        return /^(smallint|integer|bigint|numeric|decimal|real|double precision|money|oid|serial|bigserial)/i.test(String(type || ""));
    }

    function isBooleanType(type) {
        return /^boolean/i.test(String(type || ""));
    }

    function newFilter() {
        return { join: "AND", col: "", op: "=", value: "" };
    }

    function newHaving() {
        return { join: "AND", agg: "SUM", col: "", op: ">", value: "" };
    }

    function newOrder() {
        return { col: "", dir: "ASC" };
    }

    function aliasPlaceholder(name, agg) {
        return agg && agg !== "NONE" ? agg.toLowerCase() + "_" + name : "alias (optional)";
    }

    function literalFor(colName, value, op) {
        var info = columnInfo(colName);
        var type = info ? info.type : "";
        var text = String(value == null ? "" : value).trim();
        if (op === "ILIKE") return quoteLiteral(text);
        if (isBooleanType(type) && /^(true|false)$/i.test(text)) return text.toLowerCase();
        if (isNumericType(type) && /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/.test(text)) return text;
        return quoteLiteral(text);
    }

    function clampedLimit() {
        var n = parseInt(state.limit, 10);
        if (isNaN(n)) n = DEFAULT_LIMIT;
        if (n < 1) n = 1;
        if (n > MAX_LIMIT) n = MAX_LIMIT;
        return n;
    }

    // ── SQL generation ─────────────────────────────────────────────────────
    function selectedColumns() {
        return state.columns.filter(function (c) {
            var cfg = state.output[c.name];
            return cfg && cfg.selected;
        });
    }

    function hasAggregates() {
        return selectedColumns().some(function (c) {
            var cfg = state.output[c.name];
            return cfg.agg && cfg.agg !== "NONE";
        });
    }

    function buildConditions(rows, allowNullOps) {
        var parts = [];
        var skipped = 0;
        rows.forEach(function (row) {
            var rawValue = String(row.value == null ? "" : row.value).trim();
            if (!row.col) {
                // A completely blank row is the untouched default — not a mistake.
                if (rawValue) skipped += 1;
                return;
            }
            var expr;
            if (allowNullOps && NULL_OPS[row.op]) {
                expr = quoteIdent(row.col) + " " + row.op;
            } else if (rawValue === "") {
                skipped += 1;
                return;
            } else {
                expr = quoteIdent(row.col) + " " + row.op + " " + literalFor(row.col, row.value, row.op);
            }
            var join = parts.length ? (row.join === "OR" ? " OR " : " AND ") : "";
            parts.push(join + expr);
        });
        return { sql: parts.join(""), skipped: skipped };
    }

    function buildSql() {
        if (!state.table || state.loadingColumns) {
            return { sql: "", skippedWhere: 0, skippedHaving: 0, limitClamped: false };
        }

        var output = selectedColumns().map(function (c) {
            var cfg = state.output[c.name];
            var expr = quoteIdent(c.name);
            if (cfg.agg && cfg.agg !== "NONE") expr = cfg.agg + "(" + expr + ")";
            var alias = String(cfg.alias || "").trim();
            if (!alias && cfg.agg && cfg.agg !== "NONE") alias = cfg.agg.toLowerCase() + "_" + c.name;
            if (alias) expr += " AS " + quoteIdent(alias);
            return expr;
        });

        var sql = "SELECT " + (state.distinct ? "DISTINCT " : "") +
            (output.length ? output.join(", ") : "*");
        sql += "\nFROM " + quoteIdent(state.table);

        var where = buildConditions(state.where, true);
        if (where.sql) sql += "\nWHERE " + where.sql;

        if (state.groupBy.length) {
            sql += "\nGROUP BY " + state.groupBy.map(quoteIdent).join(", ");
        }

        var skippedHaving = 0;
        if (state.having.length) {
            var hp = [];
            state.having.forEach(function (row) {
                var rawValue = String(row.value == null ? "" : row.value).trim();
                if (!row.col) {
                    if (rawValue) skippedHaving += 1;
                    return;
                }
                if (rawValue === "") {
                    skippedHaving += 1;
                    return;
                }
                var expr = row.agg + "(" + quoteIdent(row.col) + ") " + row.op + " " +
                    literalFor(row.col, row.value, row.op);
                hp.push((hp.length ? (row.join === "OR" ? " OR " : " AND ") : "") + expr);
            });
            if (hp.length) sql += "\nHAVING " + hp.join("");
        }

        var order = state.orderBy.filter(function (o) { return o.col; }).map(function (o) {
            return quoteIdent(o.col) + " " + (o.dir === "DESC" ? "DESC" : "ASC");
        });
        if (order.length) sql += "\nORDER BY " + order.join(", ");

        var supplied = state.limit;
        sql += "\nLIMIT " + clampedLimit();

        return {
            sql: sql,
            skippedWhere: where.skipped,
            skippedHaving: skippedHaving,
            limitClamped: String(supplied) !== String(clampedLimit())
        };
    }

    // ── Rendering ──────────────────────────────────────────────────────────
    function renderTableOptions() {
        var html = '<option value="">' + (state.tablesLoaded ? "Select a table…" : "Loading tables…") + "</option>";
        state.tables.forEach(function (t) {
            html += '<option value="' + esc(t.name) + '"' +
                (t.name === state.table ? " selected" : "") + ">" + esc(t.name) + "</option>";
        });
        el.table.innerHTML = html;
        el.table.disabled = !state.tablesLoaded;
    }

    function columnOptions(selected) {
        return '<option value="">Column…</option>' + state.columns.map(function (c) {
            return '<option value="' + esc(c.name) + '"' +
                (c.name === selected ? " selected" : "") + ">" + esc(c.name) + "</option>";
        }).join("");
    }

    function aggOptions(selected) {
        return AGGREGATES.map(function (a) {
            return '<option value="' + a + '"' + (a === selected ? " selected" : "") + ">" + a + "</option>";
        }).join("");
    }

    function opOptions(list, selected) {
        return list.map(function (op) {
            return '<option value="' + esc(op) + '"' + (op === selected ? " selected" : "") + ">" +
                esc(op) + "</option>";
        }).join("");
    }

    function renderColumns() {
        if (!state.table) {
            el.colList.innerHTML = '<div class="qb-empty-note">Choose a table to load its columns.</div>';
            el.colCount.textContent = "";
            return;
        }
        if (state.loadingColumns) {
            el.colList.innerHTML = '<div class="qb-empty-note"><i class="fas fa-circle-notch fa-spin"></i> Loading columns…</div>';
            el.colCount.textContent = "";
            return;
        }
        if (!state.columns.length) {
            el.colList.innerHTML = '<div class="qb-empty-note">No columns reported for this table.</div>';
            el.colCount.textContent = "";
            return;
        }

        var term = String(el.colFilter.value || "").trim().toLowerCase();
        var rows = state.columns.filter(function (c) {
            return !term || c.name.toLowerCase().indexOf(term) !== -1 || String(c.type || "").toLowerCase().indexOf(term) !== -1;
        });
        el.colCount.textContent = term
            ? rows.length + " / " + state.columns.length
            : String(state.columns.length);

        if (!rows.length) {
            el.colList.innerHTML = '<div class="qb-empty-note">No column matches “' + esc(term) + '”.</div>';
            return;
        }

        el.colList.innerHTML = rows.map(function (c) {
            var cfg = state.output[c.name] || { selected: false, agg: "NONE", alias: "" };
            return '<div class="qb-col-row" data-col="' + esc(c.name) + '">' +
                '<label class="qb-col-pick" title="' + esc(c.name + " · " + c.type + (c.nullable ? " · NULL" : " · NOT NULL") + (c.is_pk ? " · primary key" : "")) + '">' +
                    '<input type="checkbox" data-role="pick" aria-label="Include ' + esc(c.name) + ' in output"' + (cfg.selected ? " checked" : "") + ">" +
                    '<span class="qb-col-name">' + esc(c.name) + "</span>" +
                    (c.is_pk ? '<span class="qb-pk" title="primary key"><i class="fas fa-key"></i></span>' : "") +
                "</label>" +
                '<span class="qb-col-type" title="' + esc(c.type) + '">' + esc(c.type) + "</span>" +
                '<select class="qb-inp qb-agg" data-role="agg" aria-label="Aggregate for ' + esc(c.name) + '">' + aggOptions(cfg.agg) + "</select>" +
                '<input class="qb-inp qb-alias" data-role="alias" type="text" spellcheck="false" value="' + esc(cfg.alias) +
                    '" placeholder="' + esc(aliasPlaceholder(c.name, cfg.agg)) + '" aria-label="Alias for ' + esc(c.name) + '">' +
                "</div>";
        }).join("");
    }

    function renderWhere() {
        if (!state.table) {
            el.whereList.innerHTML = '<div class="qb-empty-note">Choose a table to add filters.</div>';
            return;
        }
        el.whereList.innerHTML = state.where.map(function (row, index) {
            var noValue = !!NULL_OPS[row.op];
            var join = index === 0
                ? '<span class="qb-join-first">WHERE</span>'
                : '<select class="qb-inp" data-role="join" aria-label="Combine filter ' + (index + 1) + '">' +
                    opOptions(["AND", "OR"], row.join) + "</select>";
            return '<div class="qb-rule" data-idx="' + index + '">' +
                join +
                '<select class="qb-inp qb-grow" data-role="col" aria-label="Filter field ' + (index + 1) + '">' + columnOptions(row.col) + "</select>" +
                '<select class="qb-inp qb-op" data-role="op" aria-label="Operator for filter ' + (index + 1) + '">' + opOptions(OPERATORS, row.op) + "</select>" +
                '<input class="qb-inp qb-grow" data-role="value" type="text" spellcheck="false" value="' + esc(row.value) +
                    '" placeholder="' + (noValue ? "not used" : (row.op === "ILIKE" ? "%pattern%" : "value")) + '" aria-label="Value for filter ' + (index + 1) + '"' +
                    (noValue ? " disabled" : "") + ">" +
                '<button type="button" class="qb-remove" data-role="remove" title="Remove filter" aria-label="Remove filter ' + (index + 1) + '">' +
                    '<i class="fas fa-xmark"></i></button>' +
                "</div>";
        }).join("");
    }

    function renderGroup() {
        if (!state.table || !state.columns.length) {
            el.groupList.innerHTML = '<div class="qb-empty-note">Choose a table to group its columns.</div>';
            return;
        }
        el.groupList.innerHTML = '<div class="qb-chips">' + state.columns.map(function (c) {
            var on = state.groupBy.indexOf(c.name) !== -1;
            return '<label class="qb-chipbox' + (on ? " is-on" : "") + '" title="GROUP BY ' + esc(c.name) + '">' +
                '<input type="checkbox" data-role="group" value="' + esc(c.name) + '"' + (on ? " checked" : "") + ">" +
                "<span>" + esc(c.name) + "</span></label>";
        }).join("") + "</div>";
    }

    function renderHaving() {
        if (!state.table) {
            el.havingList.innerHTML = '<div class="qb-empty-note">Choose a table to filter aggregates.</div>';
            return;
        }
        if (!state.having.length) {
            el.havingList.innerHTML = '<div class="qb-empty-note">No HAVING filter. Requires GROUP BY with an aggregated column.</div>';
            return;
        }
        el.havingList.innerHTML = state.having.map(function (row, index) {
            var join = index === 0
                ? '<span class="qb-join-first">HAVING</span>'
                : '<select class="qb-inp" data-role="join" aria-label="Combine HAVING filter ' + (index + 1) + '">' +
                    opOptions(["AND", "OR"], row.join) + "</select>";
            return '<div class="qb-rule" data-idx="' + index + '">' +
                join +
                '<select class="qb-inp qb-op" data-role="agg" aria-label="Aggregate for HAVING ' + (index + 1) + '">' +
                    aggOptions(row.agg).replace('<option value="NONE">NONE</option>', "") + "</select>" +
                '<select class="qb-inp qb-grow" data-role="col" aria-label="HAVING field ' + (index + 1) + '">' + columnOptions(row.col) + "</select>" +
                '<select class="qb-inp qb-op" data-role="op" aria-label="HAVING operator ' + (index + 1) + '">' + opOptions(HAVING_OPERATORS, row.op) + "</select>" +
                '<input class="qb-inp qb-grow" data-role="value" type="text" spellcheck="false" value="' + esc(row.value) +
                    '" placeholder="value" aria-label="HAVING value ' + (index + 1) + '">' +
                '<button type="button" class="qb-remove" data-role="remove" title="Remove HAVING filter" aria-label="Remove HAVING filter ' + (index + 1) + '">' +
                    '<i class="fas fa-xmark"></i></button>' +
                "</div>";
        }).join("");
    }

    function renderOrder() {
        if (!state.table) {
            el.orderList.innerHTML = '<div class="qb-empty-note">Choose a table to sort its columns.</div>';
            return;
        }
        el.orderList.innerHTML = state.orderBy.map(function (row, index) {
            var join = index === 0
                ? '<span class="qb-join-first">ORDER BY</span>'
                : '<span class="qb-join-first qb-then">THEN</span>';
            return '<div class="qb-rule" data-idx="' + index + '">' +
                join +
                '<select class="qb-inp qb-grow" data-role="col" aria-label="Sort field ' + (index + 1) + '">' + columnOptions(row.col) + "</select>" +
                '<select class="qb-inp qb-op" data-role="dir" aria-label="Sort direction ' + (index + 1) + '">' +
                    opOptions(["ASC", "DESC"], row.dir) + "</select>" +
                '<button type="button" class="qb-remove" data-role="remove" title="Remove sort" aria-label="Remove sort ' + (index + 1) + '">' +
                    '<i class="fas fa-xmark"></i></button>' +
                "</div>";
        }).join("");
    }

    function updatePreview() {
        var result = buildSql();
        var sql = result.sql;
        el.preview.textContent = sql || "-- Pick a table to generate a SELECT.";

        var notes = [];
        if (!state.table) {
            notes.push("Choose a table to start building.");
        } else if (result.skippedWhere || result.skippedHaving) {
            var total = (result.skippedWhere || 0) + (result.skippedHaving || 0);
            notes.push(total + " incomplete filter" + (total === 1 ? " is" : "s are") +
                " ignored in the preview — pick a column and a value.");
        }
        if (state.table && hasAggregates() && !state.groupBy.length) {
            notes.push("Aggregates selected without GROUP BY: Postgres will reject any plain column in the output. Group every non-aggregated column.");
        }
        if (result.limitClamped) {
            notes.push("LIMIT is clamped to 1–" + MAX_LIMIT + " (default " + DEFAULT_LIMIT + ").");
        }
        el.note.innerHTML = notes.map(function (n) { return "<div>• " + esc(n) + "</div>"; }).join("");

        var blocked = !state.table || state.loadingColumns;
        el.build.disabled = blocked;
        el.buildRun.disabled = blocked;
    }

    function renderAll() {
        renderTableOptions();
        renderColumns();
        renderWhere();
        renderGroup();
        renderHaving();
        renderOrder();
        updatePreview();
    }

    // ── Metadata loading ───────────────────────────────────────────────────
    function fetchJson(url) {
        return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
            return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
        });
    }

    function guessTable() {
        if (!el.sql) return "";
        var value = el.sql.value || "";
        var match = /\bFROM\s+(?:"public"\s*\.\s*)?"([^"]+)"/i.exec(value);
        if (!match) match = /\bFROM\s+(?:"public"\s*\.\s*)?([A-Za-z_][\w$]*)/i.exec(value);
        if (!match) return "";
        var name = match[1];
        for (var i = 0; i < state.tables.length; i += 1) {
            if (state.tables[i].name === name) return name;
        }
        return "";
    }

    function loadTables() {
        if (state.tablesLoaded) return;
        fetchJson("/api/query_db/tables").then(function (res) {
            if (!res.ok || !res.d || res.d.status !== "success") {
                el.table.innerHTML = '<option value="">Tables unavailable</option>';
                el.table.disabled = true;
                updatePreview();
                return;
            }
            state.tables = (res.d.tables || []).filter(function (t) { return t && t.name; });
            state.tablesLoaded = true;
            renderTableOptions();
            if (!state.table) {
                var guess = guessTable();
                if (guess) selectTable(guess);
                else updatePreview();
            }
        }).catch(function () {
            el.table.innerHTML = '<option value="">Could not load tables</option>';
            el.table.disabled = true;
            updatePreview();
        });
    }

    function resetBuilder() {
        state.columns = [];
        state.output = {};
        state.where = [newFilter()];
        state.groupBy = [];
        state.having = [];
        state.orderBy = [newOrder()];
        state.distinct = false;
        state.limit = DEFAULT_LIMIT;
        if (el.distinct) el.distinct.checked = false;
        if (el.limit) el.limit.value = String(DEFAULT_LIMIT);
        if (el.colFilter) el.colFilter.value = "";
    }

    function applyColumns(columns) {
        state.loadingColumns = false;
        state.columns = columns.slice();
        state.output = {};
        state.columns.forEach(function (c) {
            state.output[c.name] = { selected: false, agg: "NONE", alias: "" };
        });
        state.where = [newFilter()];
        state.groupBy = [];
        state.having = [];
        state.orderBy = [newOrder()];
        renderAll();
    }

    function selectTable(name) {
        state.table = name || "";
        resetBuilder();
        if (el.table) el.table.value = state.table;

        if (!state.table) {
            state.loadingColumns = false;
            renderAll();
            return;
        }
        if (cache[name]) {
            applyColumns(cache[name]);
            return;
        }

        state.loadingColumns = true;
        renderAll();
        fetchJson("/api/query_db/columns?table=" + encodeURIComponent(name)).then(function (res) {
            if (state.table !== name) return;
            if (!res.ok || !res.d || res.d.status !== "success") {
                state.loadingColumns = false;
                state.columns = [];
                el.colList.innerHTML = '<div class="qb-empty-note">' +
                    esc((res.d && res.d.message) || "Could not read columns for this table.") + "</div>";
                updatePreview();
                return;
            }
            cache[name] = res.d.columns || [];
            applyColumns(cache[name]);
        }).catch(function () {
            if (state.table !== name) return;
            state.loadingColumns = false;
            state.columns = [];
            el.colList.innerHTML = '<div class="qb-empty-note">Network error while loading columns.</div>';
            updatePreview();
        });
    }

    // ── Dialog lifecycle ───────────────────────────────────────────────────
    function openBuilder() {
        // Always return focus to the toolbar trigger, even when the click did
        // not move DOM focus there (pointer interaction on some browsers).
        lastFocus = el.open || document.activeElement;
        loadTables();
        renderAll();
        if (!el.dialog.open) {
            if (typeof el.dialog.showModal === "function") el.dialog.showModal();
            else el.dialog.setAttribute("open", "");
        }
        setTimeout(function () {
            if (el.table && !el.table.disabled) el.table.focus();
            else el.dialog.focus();
        }, 0);
    }

    function closeBuilder(useSql, run) {
        var sql = "";
        var willRun = !!run;
        if (useSql) {
            sql = buildSql().sql;
            if (!sql) return;
            el.sql.value = sql;
            el.sql.setSelectionRange(sql.length, sql.length);
            pendingFocus = el.sql;
            pendingRun = willRun;
        } else {
            pendingFocus = lastFocus;
            pendingRun = false;
        }

        var wasOpen = !!el.dialog.open;
        if (wasOpen && typeof el.dialog.close === "function") {
            try {
                el.dialog.close();
            } catch (err) {
                el.dialog.removeAttribute("open");
                afterClose();
                return;
            }
            // Some environments / polyfills do not reliably dispatch the
            // native 'close' event synchronously or at all when closing via API.
            // Run afterClose via requestAnimationFrame/setTimeout as an idempotent fallback.
            setTimeout(function () {
                if (pendingRun || pendingFocus) afterClose();
            }, 0);
        } else {
            el.dialog.removeAttribute("open");
            afterClose();
        }
    }

    function afterClose() {
        var target = pendingFocus || lastFocus || el.open;
        pendingFocus = null;
        if (target && typeof target.focus === "function") {
            try { target.focus(); } catch (err) { /* ignore focus races */ }
        }
        if (pendingRun) {
            pendingRun = false;
            if (el.run && !el.run.disabled) el.run.click();
        }
    }

    function copySql() {
        var text = el.preview.textContent || "";
        var done = function () {
            var previous = el.copy.innerHTML;
            el.copy.innerHTML = '<i class="fas fa-check"></i> Copied';
            setTimeout(function () { el.copy.innerHTML = previous; }, 1500);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done, function () { el.copy.focus(); });
            return;
        }
        var ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); done(); } catch (err) { /* clipboard unavailable */ }
        document.body.removeChild(ta);
    }

    // ── Event wiring ───────────────────────────────────────────────────────
    function bind() {
        el.open.addEventListener("click", openBuilder);
        el.close.addEventListener("click", function () { closeBuilder(false, false); });
        el.cancel.addEventListener("click", function () { closeBuilder(false, false); });
        el.build.addEventListener("click", function () { closeBuilder(true, false); });
        el.buildRun.addEventListener("click", function () { closeBuilder(true, true); });
        el.dialog.addEventListener("cancel", function (ev) {
            ev.preventDefault();
            closeBuilder(false, false);
        });
        el.dialog.addEventListener("close", afterClose);

        el.table.addEventListener("change", function () { selectTable(el.table.value); });
        el.distinct.addEventListener("change", function () {
            state.distinct = !!el.distinct.checked;
            updatePreview();
        });
        el.limit.addEventListener("input", function () {
            state.limit = el.limit.value;
            updatePreview();
        });
        el.limit.addEventListener("blur", function () {
            state.limit = clampedLimit();
            el.limit.value = String(state.limit);
            updatePreview();
        });
        el.colFilter.addEventListener("input", renderColumns);
        el.copy.addEventListener("click", copySql);

        el.selectAll.addEventListener("click", function () {
            state.columns.forEach(function (c) {
                if (state.output[c.name]) state.output[c.name].selected = true;
            });
            renderColumns();
            updatePreview();
        });
        el.selectNone.addEventListener("click", function () {
            state.columns.forEach(function (c) {
                if (state.output[c.name]) state.output[c.name].selected = false;
            });
            renderColumns();
            updatePreview();
        });

        el.colList.addEventListener("change", function (ev) {
            var row = ev.target.closest(".qb-col-row");
            if (!row) return;
            var name = row.getAttribute("data-col");
            var cfg = state.output[name];
            if (!cfg) return;
            if (ev.target.getAttribute("data-role") === "pick") {
                cfg.selected = !!ev.target.checked;
            } else if (ev.target.getAttribute("data-role") === "agg") {
                cfg.agg = ev.target.value;
                var alias = row.querySelector('[data-role="alias"]');
                if (alias) alias.placeholder = aliasPlaceholder(name, cfg.agg);
            }
            updatePreview();
        });
        el.colList.addEventListener("input", function (ev) {
            var row = ev.target.closest(".qb-col-row");
            if (!row) return;
            var name = row.getAttribute("data-col");
            var cfg = state.output[name];
            if (!cfg) return;
            if (ev.target.getAttribute("data-role") === "alias") {
                cfg.alias = ev.target.value;
                updatePreview();
            }
        });

        el.whereList.addEventListener("change", function (ev) {
            var row = ev.target.closest(".qb-rule");
            if (!row) return;
            var item = state.where[Number(row.getAttribute("data-idx"))];
            if (!item) return;
            var role = ev.target.getAttribute("data-role");
            if (!role) return;
            if (role === "remove") return;
            item[role] = ev.target.value;
            if (role === "op") renderWhere();
            updatePreview();
        });
        el.whereList.addEventListener("input", function (ev) {
            if (ev.target.getAttribute("data-role") !== "value") return;
            var row = ev.target.closest(".qb-rule");
            var item = row ? state.where[Number(row.getAttribute("data-idx"))] : null;
            if (!item) return;
            item.value = ev.target.value;
            updatePreview();
        });
        el.whereList.addEventListener("click", function (ev) {
            var btn = ev.target.closest('[data-role="remove"]');
            if (!btn) return;
            var row = btn.closest(".qb-rule");
            state.where.splice(Number(row.getAttribute("data-idx")), 1);
            if (!state.where.length) state.where.push(newFilter());
            renderWhere();
            updatePreview();
        });
        el.addWhere.addEventListener("click", function () {
            state.where.push(newFilter());
            renderWhere();
            updatePreview();
            var rows = el.whereList.querySelectorAll(".qb-rule");
            var last = rows[rows.length - 1];
            if (last) last.querySelector('[data-role="col"]').focus();
        });

        el.groupList.addEventListener("change", function (ev) {
            if (ev.target.getAttribute("data-role") !== "group") return;
            var name = ev.target.value;
            var at = state.groupBy.indexOf(name);
            if (ev.target.checked && at === -1) state.groupBy.push(name);
            if (!ev.target.checked && at !== -1) state.groupBy.splice(at, 1);
            var label = ev.target.closest(".qb-chipbox");
            if (label) label.classList.toggle("is-on", !!ev.target.checked);
            updatePreview();
        });

        el.havingList.addEventListener("change", function (ev) {
            var row = ev.target.closest(".qb-rule");
            if (!row) return;
            var item = state.having[Number(row.getAttribute("data-idx"))];
            if (!item) return;
            var role = ev.target.getAttribute("data-role");
            if (!role || role === "remove") return;
            item[role] = ev.target.value;
            updatePreview();
        });
        el.havingList.addEventListener("input", function (ev) {
            if (ev.target.getAttribute("data-role") !== "value") return;
            var row = ev.target.closest(".qb-rule");
            var item = row ? state.having[Number(row.getAttribute("data-idx"))] : null;
            if (!item) return;
            item.value = ev.target.value;
            updatePreview();
        });
        el.havingList.addEventListener("click", function (ev) {
            var btn = ev.target.closest('[data-role="remove"]');
            if (!btn) return;
            var row = btn.closest(".qb-rule");
            state.having.splice(Number(row.getAttribute("data-idx")), 1);
            renderHaving();
            updatePreview();
        });
        el.addHaving.addEventListener("click", function () {
            state.having.push(newHaving());
            renderHaving();
            updatePreview();
            var rows = el.havingList.querySelectorAll(".qb-rule");
            var last = rows[rows.length - 1];
            if (last) last.querySelector('[data-role="col"]').focus();
        });

        el.orderList.addEventListener("change", function (ev) {
            var row = ev.target.closest(".qb-rule");
            if (!row) return;
            var item = state.orderBy[Number(row.getAttribute("data-idx"))];
            if (!item) return;
            var role = ev.target.getAttribute("data-role");
            if (!role || role === "remove") return;
            item[role] = ev.target.value;
            updatePreview();
        });
        el.orderList.addEventListener("click", function (ev) {
            var btn = ev.target.closest('[data-role="remove"]');
            if (!btn) return;
            var row = btn.closest(".qb-rule");
            state.orderBy.splice(Number(row.getAttribute("data-idx")), 1);
            if (!state.orderBy.length) state.orderBy.push(newOrder());
            renderOrder();
            updatePreview();
        });
        el.addOrder.addEventListener("click", function () {
            state.orderBy.push(newOrder());
            renderOrder();
            updatePreview();
            var rows = el.orderList.querySelectorAll(".qb-rule");
            var last = rows[rows.length - 1];
            if (last) last.querySelector('[data-role="col"]').focus();
        });
    }

    function init() {
        el.dialog = document.getElementById("qdbBuilderDialog");
        if (!el.dialog) return;

        el.open = document.getElementById("qdbBuilderOpen");
        el.close = document.getElementById("qbClose");
        el.cancel = document.getElementById("qbCancel");
        el.build = document.getElementById("qbBuild");
        el.buildRun = document.getElementById("qbBuildRun");
        el.table = document.getElementById("qbTable");
        el.distinct = document.getElementById("qbDistinct");
        el.limit = document.getElementById("qbLimit");
        el.colFilter = document.getElementById("qbColumnFilter");
        el.colList = document.getElementById("qbColumnList");
        el.colCount = document.getElementById("qbColumnCount");
        el.selectAll = document.getElementById("qbSelectAll");
        el.selectNone = document.getElementById("qbSelectNone");
        el.whereList = document.getElementById("qbWhereRows");
        el.addWhere = document.getElementById("qbAddWhere");
        el.groupList = document.getElementById("qbGroupList");
        el.havingList = document.getElementById("qbHavingRows");
        el.addHaving = document.getElementById("qbAddHaving");
        el.orderList = document.getElementById("qbOrderRows");
        el.addOrder = document.getElementById("qbAddOrder");
        el.preview = document.getElementById("qbSqlPreview");
        el.note = document.getElementById("qbNote");
        el.copy = document.getElementById("qbCopySql");
        el.sql = document.getElementById("qdbSql");
        el.run = document.getElementById("qdbRun");

        var required = ["open", "close", "cancel", "build", "buildRun", "table", "distinct",
            "limit", "colFilter", "colList", "colCount", "selectAll", "selectNone", "whereList",
            "addWhere", "groupList", "havingList", "addHaving", "orderList", "addOrder",
            "preview", "note", "copy"];
        for (var i = 0; i < required.length; i += 1) {
            if (!el[required[i]]) {
                if (window.console && console.warn) {
                    console.warn("Query Builder: missing element", required[i]);
                }
                return;
            }
        }

        bind();
        state.where = [newFilter()];
        state.orderBy = [newOrder()];
        renderAll();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
