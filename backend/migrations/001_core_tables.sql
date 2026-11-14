-- 核心表结构参考（PostgreSQL 语法，运行时不执行；建表由 SQLAlchemy create_all 完成）

CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(160) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    display_name    VARCHAR(80)  NOT NULL,
    role            VARCHAR(20)  NOT NULL,
    team_id         INTEGER      REFERENCES teams(id) ON DELETE SET NULL,
    org             VARCHAR(120),
    created_at      TIMESTAMP    NOT NULL
);

CREATE TABLE teams (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(40)  NOT NULL UNIQUE,
    name            VARCHAR(120) NOT NULL,
    budget_yuan     DOUBLE PRECISION NOT NULL DEFAULT 0,
    cost_center     VARCHAR(40)  NOT NULL,
    owner           VARCHAR(80)  NOT NULL,
    prev_month_yuan DOUBLE PRECISION NOT NULL DEFAULT 0,
    member_count    INTEGER      NOT NULL DEFAULT 0,
    note            TEXT,
    created_at      TIMESTAMP    NOT NULL,
    updated_at      TIMESTAMP    NOT NULL
);

CREATE TABLE query_logs (
    id              SERIAL PRIMARY KEY,
    query_id        VARCHAR(64)  NOT NULL UNIQUE,
    user_email      VARCHAR(160) NOT NULL,
    team_id         INTEGER      NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    sql_digest      VARCHAR(160) NOT NULL,
    scanned_gb      DOUBLE PRECISION NOT NULL DEFAULT 0,
    duration_ms     INTEGER      NOT NULL DEFAULT 0,
    cache_hit       BOOLEAN      NOT NULL DEFAULT FALSE,
    status          VARCHAR(16)  NOT NULL DEFAULT 'success',
    queried_at      TIMESTAMP    NOT NULL,
    cost_yuan       DOUBLE PRECISION NOT NULL DEFAULT 0,
    is_anomaly      BOOLEAN      NOT NULL DEFAULT FALSE,
    anomaly_score   DOUBLE PRECISION NOT NULL DEFAULT 0,
    anomaly_reason  TEXT,
    seed_key        VARCHAR(120) UNIQUE,
    created_at      TIMESTAMP    NOT NULL
);

CREATE TABLE cost_runs (
    id              SERIAL PRIMARY KEY,
    run_no          VARCHAR(40)  NOT NULL UNIQUE,
    period          VARCHAR(20)  NOT NULL,
    scan_price      DOUBLE PRECISION NOT NULL DEFAULT 0.028,
    compute_price   DOUBLE PRECISION NOT NULL DEFAULT 0.0004,
    cache_discount  DOUBLE PRECISION NOT NULL DEFAULT 0.3,
    trigger         VARCHAR(20)  NOT NULL DEFAULT 'manual',
    status          VARCHAR(20)  NOT NULL,
    operator_email  VARCHAR(160) NOT NULL,
    input_count     INTEGER      NOT NULL DEFAULT 0,
    output_count    INTEGER      NOT NULL DEFAULT 0,
    total_cost_yuan DOUBLE PRECISION NOT NULL DEFAULT 0,
    metrics         JSON,
    log_text        TEXT,
    seed_key        VARCHAR(120) UNIQUE,
    started_at      TIMESTAMP    NOT NULL,
    finished_at     TIMESTAMP
);

CREATE TABLE charges (
    id                SERIAL PRIMARY KEY,
    run_id            INTEGER NOT NULL REFERENCES cost_runs(id) ON DELETE CASCADE,
    team_id           INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    amount_yuan       DOUBLE PRECISION NOT NULL DEFAULT 0,
    ratio             DOUBLE PRECISION NOT NULL DEFAULT 0,
    query_count       INTEGER NOT NULL DEFAULT 0,
    cached_saved_yuan DOUBLE PRECISION NOT NULL DEFAULT 0,
    mom_ratio         DOUBLE PRECISION,
    user_split        JSON,
    top_query         JSON,
    created_at        TIMESTAMP NOT NULL,
    CONSTRAINT uq_charges_run_team UNIQUE (run_id, team_id)
);

CREATE TABLE budget_alerts (
    id             SERIAL PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES cost_runs(id) ON DELETE CASCADE,
    team_id        INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    forecast_yuan  DOUBLE PRECISION NOT NULL DEFAULT 0,
    ratio          DOUBLE PRECISION NOT NULL DEFAULT 0,
    level          VARCHAR(16) NOT NULL DEFAULT 'normal',
    gate_action    VARCHAR(24) NOT NULL DEFAULT 'watch',
    status         VARCHAR(16) NOT NULL DEFAULT 'pending',
    note           TEXT,
    reviewer       VARCHAR(160),
    reviewed_at    TIMESTAMP,
    created_at     TIMESTAMP NOT NULL,
    CONSTRAINT uq_alerts_run_team UNIQUE (run_id, team_id)
);

CREATE TABLE audit_logs (
    id              SERIAL PRIMARY KEY,
    actor_email     VARCHAR(160) NOT NULL,
    actor_role      VARCHAR(20)  NOT NULL,
    action          VARCHAR(64)  NOT NULL,
    entity          VARCHAR(40)  NOT NULL,
    entity_id       VARCHAR(64),
    detail          JSON,
    layer           VARCHAR(16)  NOT NULL DEFAULT 'domain',
    ip              VARCHAR(64),
    seed_key        VARCHAR(120) UNIQUE,
    created_at      TIMESTAMP    NOT NULL
);

-- 供应商对账：账单头 / 账单行 / 核对批次 / 差异明细 / 账期修正台账
CREATE TABLE supplier_bills (
    id               SERIAL PRIMARY KEY,
    bill_no          VARCHAR(64)  NOT NULL UNIQUE,
    vendor           VARCHAR(120) NOT NULL DEFAULT 'clickhouse-cloud',
    period           VARCHAR(20)  NOT NULL,
    source_filename  VARCHAR(255) NOT NULL DEFAULT '',
    file_hash        VARCHAR(64)  NOT NULL UNIQUE,
    line_count       INTEGER      NOT NULL DEFAULT 0,
    total_amount_yuan DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_scanned_gb DOUBLE PRECISION NOT NULL DEFAULT 0,
    status           VARCHAR(20)  NOT NULL DEFAULT 'imported',
    error_message    TEXT,
    confirmed_at     TIMESTAMP,
    confirmed_by     VARCHAR(160),
    published_run_id INTEGER,
    created_at       TIMESTAMP    NOT NULL,
    updated_at       TIMESTAMP    NOT NULL
);
CREATE INDEX idx_supplier_bills_period ON supplier_bills(period);
CREATE INDEX idx_supplier_bills_status ON supplier_bills(status);

CREATE TABLE supplier_bill_items (
    id            SERIAL PRIMARY KEY,
    bill_id       INTEGER NOT NULL REFERENCES supplier_bills(id) ON DELETE CASCADE,
    query_id      VARCHAR(64) NOT NULL,
    team_code     VARCHAR(40) NOT NULL,
    user_email    VARCHAR(160) NOT NULL DEFAULT '',
    scanned_gb    DOUBLE PRECISION NOT NULL DEFAULT 0,
    unit_price    DOUBLE PRECISION NOT NULL DEFAULT 0,
    amount_yuan   DOUBLE PRECISION NOT NULL DEFAULT 0,
    queried_at    TIMESTAMP,
    duplicate_seq INTEGER NOT NULL DEFAULT 1,
    raw_line      VARCHAR(1000) NOT NULL DEFAULT '',
    created_at    TIMESTAMP NOT NULL
);
CREATE INDEX idx_supplier_bill_items_bill ON supplier_bill_items(bill_id);
CREATE INDEX idx_supplier_bill_items_query ON supplier_bill_items(query_id);
CREATE INDEX idx_supplier_bill_items_team ON supplier_bill_items(team_code);

CREATE TABLE reconciliation_runs (
    id                  SERIAL PRIMARY KEY,
    recon_no            VARCHAR(40) NOT NULL UNIQUE,
    bill_id             INTEGER NOT NULL REFERENCES supplier_bills(id) ON DELETE CASCADE,
    period              VARCHAR(20) NOT NULL,
    operator_email      VARCHAR(160) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'running',
    bill_total_yuan     DOUBLE PRECISION NOT NULL DEFAULT 0,
    platform_total_yuan DOUBLE PRECISION NOT NULL DEFAULT 0,
    diff_total_yuan     DOUBLE PRECISION NOT NULL DEFAULT 0,
    diff_counts         JSON,
    error_message       TEXT,
    started_at          TIMESTAMP NOT NULL,
    finished_at         TIMESTAMP,
    created_at          TIMESTAMP NOT NULL
);
CREATE INDEX idx_recon_runs_bill ON reconciliation_runs(bill_id);
CREATE INDEX idx_recon_runs_period ON reconciliation_runs(period);
CREATE INDEX idx_recon_runs_status ON reconciliation_runs(status);

CREATE TABLE reconciliation_findings (
    id                   SERIAL PRIMARY KEY,
    run_id               INTEGER NOT NULL REFERENCES reconciliation_runs(id) ON DELETE CASCADE,
    bill_id              INTEGER NOT NULL REFERENCES supplier_bills(id) ON DELETE CASCADE,
    period               VARCHAR(20) NOT NULL,
    query_id             VARCHAR(64) NOT NULL,
    team_code            VARCHAR(40),
    user_email           VARCHAR(160),
    diff_type            VARCHAR(24) NOT NULL,
    duplicate_seq        INTEGER NOT NULL DEFAULT 1,
    status               VARCHAR(16) NOT NULL DEFAULT 'open',
    bill_scanned_gb      DOUBLE PRECISION NOT NULL DEFAULT 0,
    platform_scanned_gb  DOUBLE PRECISION NOT NULL DEFAULT 0,
    bill_amount_yuan     DOUBLE PRECISION NOT NULL DEFAULT 0,
    platform_amount_yuan DOUBLE PRECISION NOT NULL DEFAULT 0,
    diff_amount_yuan     DOUBLE PRECISION NOT NULL DEFAULT 0,
    bill_unit_price      DOUBLE PRECISION NOT NULL DEFAULT 0,
    platform_unit_price  DOUBLE PRECISION NOT NULL DEFAULT 0,
    detail               JSON,
    note                 TEXT,
    resolver             VARCHAR(160),
    resolved_at          TIMESTAMP,
    created_at           TIMESTAMP NOT NULL,
    CONSTRAINT uq_finding_run_bill_query_type UNIQUE (run_id, bill_id, query_id, diff_type, duplicate_seq)
);
CREATE INDEX idx_recon_findings_bill ON reconciliation_findings(bill_id);
CREATE INDEX idx_recon_findings_type ON reconciliation_findings(diff_type);
CREATE INDEX idx_recon_findings_status ON reconciliation_findings(status);
CREATE INDEX idx_recon_findings_period ON reconciliation_findings(period);

CREATE TABLE bill_adjustments (
    id                 SERIAL PRIMARY KEY,
    bill_id            INTEGER NOT NULL REFERENCES supplier_bills(id) ON DELETE CASCADE,
    run_id             INTEGER,
    period             VARCHAR(20) NOT NULL,
    team_code          VARCHAR(40) NOT NULL,
    diff_type          VARCHAR(24) NOT NULL,
    amount_yuan        DOUBLE PRECISION NOT NULL DEFAULT 0,
    payable_delta_yuan DOUBLE PRECISION NOT NULL DEFAULT 0,
    finding_count      INTEGER NOT NULL DEFAULT 0,
    status             VARCHAR(16) NOT NULL DEFAULT 'applied',
    note               TEXT,
    created_by         VARCHAR(160) NOT NULL DEFAULT 'system',
    created_at         TIMESTAMP NOT NULL,
    CONSTRAINT uq_adjustment_bill_period_team_type UNIQUE (bill_id, period, team_code, diff_type)
);
CREATE INDEX idx_bill_adjustments_bill ON bill_adjustments(bill_id);
CREATE INDEX idx_bill_adjustments_period ON bill_adjustments(period);
