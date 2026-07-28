-- ForecastLens result store. Driver naming only — the word "production" must
-- not appear here. All access goes through repository.py with parameterized
-- queries.

CREATE TABLE IF NOT EXISTS run (
    run_id      TEXT PRIMARY KEY,
    run_number  INTEGER,                -- 1, 2, 3… what the user sees
    name        TEXT,
    created_at  TEXT NOT NULL,
    input_hash  TEXT,
    source_name TEXT,
    config_json TEXT NOT NULL,
    status      TEXT NOT NULL,          -- running | complete | failed
    n_series    INTEGER,
    duration_s  REAL,
    scope_note  TEXT                    -- 'all items' or the scoped subset
);

CREATE TABLE IF NOT EXISTS item (
    item_code     TEXT PRIMARY KEY,
    description   TEXT,
    uom           TEXT,
    unit_price    REAL,
    unit_wt       REAL,
    cat_l1        TEXT,
    cat_l2        TEXT,
    cat_l3        TEXT,
    declared_mode TEXT                  -- optional planner declaration in bom
);

CREATE TABLE IF NOT EXISTS series (
    series_id      TEXT PRIMARY KEY,    -- deterministic: item|line|output
    item_code      TEXT NOT NULL,
    line           TEXT,
    output_type    TEXT,
    mode           TEXT NOT NULL,       -- relative | absolute
    mode_source    TEXT NOT NULL,       -- inferred | declared_bom | declared_ui
    target_uom     TEXT,
    first_period   TEXT,
    last_period    TEXT,
    n_periods      INTEGER,             -- span length incl. gap-filled
    n_observed     INTEGER,             -- periods with real observations
    n_reliable     INTEGER,             -- periods usable for fitting
    n_applicable   INTEGER,             -- periods where the line actually ran
    is_orphan      INTEGER NOT NULL DEFAULT 0,
    pattern_class  TEXT,
    adi            REAL,
    cv2            REAL,
    trend_strength REAL,
    seasonality_strength REAL,
    stationary     INTEGER,
    autocorr_lag1  REAL,
    outlier_pct    REAL,
    missing_pct    REAL,
    structural_break_period TEXT,
    forecastability REAL,
    data_quality   REAL
);

CREATE TABLE IF NOT EXISTS observation (
    series_id     TEXT NOT NULL,
    period        TEXT NOT NULL,        -- ISO period string, e.g. 2024-01
    qty_base      REAL,
    qty_ton       REAL,
    cost          REAL,
    rate          REAL,
    driver_qty    REAL,
    target        REAL,                 -- prepared target (rate, or per-day qty)
    is_gap_filled INTEGER NOT NULL DEFAULT 0,
    is_reliable   INTEGER NOT NULL DEFAULT 1,
    -- 0 when the line did not run at all that period (no rate AND no driver):
    -- not a zero-demand observation, so it is excluded from classification
    is_applicable INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (series_id, period)
);

CREATE TABLE IF NOT EXISTS driver (
    period      TEXT NOT NULL,
    line        TEXT,
    output_type TEXT,
    driver_qty  REAL,
    driver_uom  TEXT,
    driver_type TEXT NOT NULL,          -- actual | plan
    PRIMARY KEY (period, line, output_type, driver_type)
);

CREATE TABLE IF NOT EXISTS standard_rate (
    item_code   TEXT NOT NULL,
    line        TEXT,
    output_type TEXT,
    std_rate    REAL,
    std_uom     TEXT,
    PRIMARY KEY (item_code, line, output_type)
);

CREATE TABLE IF NOT EXISTS validation_result (
    run_id      TEXT NOT NULL,
    series_id   TEXT NOT NULL,
    model_name  TEXT NOT NULL,
    window      INTEGER,                -- lookback window; NULL = full history
    mase        REAL,
    mae         REAL,
    rmse        REAL,
    mape        REAL,
    smape       REAL,
    n_origins   INTEGER,
    fit_seconds REAL,
    status      TEXT NOT NULL DEFAULT 'ok',   -- ok | failed | gated_out
    fail_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_validation_run_series
    ON validation_result (run_id, series_id);

CREATE TABLE IF NOT EXISTS selection (
    run_id          TEXT NOT NULL,
    series_id       TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    window          INTEGER,
    mase            REAL,
    confidence      REAL,
    confidence_label TEXT,              -- low | medium | high
    route           TEXT,               -- compete | cold_start | routed_…
    reason_code     TEXT,
    reason_text     TEXT,               -- plain language, planner-readable
    rejected_json   TEXT,               -- [{model, window, mase, status, reason}]
    is_override     INTEGER NOT NULL DEFAULT 0,
    override_reason TEXT,
    PRIMARY KEY (run_id, series_id)
);

CREATE TABLE IF NOT EXISTS forecast (
    run_id               TEXT NOT NULL,
    series_id            TEXT NOT NULL,
    period               TEXT NOT NULL,
    target_value         REAL,
    lower_80             REAL,
    upper_80             REAL,
    lower_95             REAL,
    upper_95             REAL,
    driver_plan          REAL,
    reconstructed_demand REAL,          -- NULL when no driver plan exists
    demand_lower_80      REAL,
    demand_upper_80      REAL,
    demand_lower_95      REAL,
    demand_upper_95      REAL,
    confidence           REAL,
    PRIMARY KEY (run_id, series_id, period)
);
CREATE INDEX IF NOT EXISTS ix_forecast_run ON forecast (run_id);

CREATE TABLE IF NOT EXISTS warning (
    run_id      TEXT,
    series_id   TEXT,
    code        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    count       INTEGER NOT NULL DEFAULT 1,
    message     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_warning_run ON warning (run_id);

-- Planner override of the selected model, sticky across runs until unlocked.
CREATE TABLE IF NOT EXISTS model_override (
    series_id  TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    reason     TEXT,
    locked     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- Planner declaration of an item's mode from the UI. Wins over bom column
-- and over inference (mode is a property of the material's nature).
CREATE TABLE IF NOT EXISTS mode_override (
    item_code  TEXT PRIMARY KEY,
    mode       TEXT NOT NULL,           -- relative | absolute
    reason     TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accuracy_history (
    series_id      TEXT NOT NULL,
    period         TEXT NOT NULL,
    forecast_value REAL,
    actual_value   REAL,
    error          REAL,
    abs_pct_error  REAL,
    model_name     TEXT,
    run_id         TEXT,
    recorded_at    TEXT NOT NULL,
    PRIMARY KEY (series_id, period, run_id)
);

-- Does the operating context move this series? Written for EVERY series on
-- every run, whether or not a context-aware model was used, so the
-- intelligence card can always answer the question.
CREATE TABLE IF NOT EXISTS series_context (
    series_id      TEXT PRIMARY KEY,
    tested         INTEGER NOT NULL DEFAULT 0,
    n_regimes      INTEGER,
    n_observations INTEGER,
    p_value        REAL,
    effect_size    REAL,               -- eta-squared
    spread_pct     REAL,               -- (highest - lowest) / overall mean
    material       INTEGER NOT NULL DEFAULT 0,
    verdict        TEXT,               -- plain language, planner-readable
    regime_counts_json TEXT,
    skip_reason    TEXT
);

-- The placeholder `event_calendar` table that used to sit here is gone:
-- promotion and event regressors are real now. They arrive through the
-- workbook's optional `context_calendar` sheet, become ordinary context
-- features, and their effect is recorded in series_context above. An older
-- database may still carry the empty table; nothing reads it.
