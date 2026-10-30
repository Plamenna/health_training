-- Schema for health data received from Health Auto Export.
-- Parquet stays the raw archive; these tables hold the cleaned, de-duplicated data.
--
-- Safe to run again: tables use IF NOT EXISTS, views are replaced, seed rows upsert.
-- Postgres runs it automatically on a fresh volume (mounted in /docker-entrypoint-initdb.d);
-- on an existing one apply it by hand:
--   docker compose exec -T db psql -U health -d health -v ON_ERROR_STOP=1 < db/schema.sql
--
-- Every time is stored as timestamptz (an exact instant). Views turn it into a local day
-- with local_day(), so the 25 Oct clock change (+02:00 -> +01:00) is handled correctly.

-- Change the timezone here if you move: every view goes through this function
CREATE OR REPLACE FUNCTION local_day(ts timestamptz) RETURNS date
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN (ts AT TIME ZONE 'Europe/Zurich')::date;

-- Shows times in local time in psql; storage is unaffected
DO $$ BEGIN
    EXECUTE format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'Europe/Zurich');
END $$;


-- ---------------------------------------------------------------------------------------
-- Health metrics: one generic table, one row per metric per time slot.
-- A metric newly ticked in the app just becomes new rows, no schema change needed.
-- ---------------------------------------------------------------------------------------

-- What each metric means and how to roll it up to a day. Not a foreign key on purpose:
-- an unknown metric must still be stored, it just falls back to an average.
CREATE TABLE IF NOT EXISTS metric_definition (
    metric      text PRIMARY KEY,
    frequency   text NOT NULL CHECK (frequency IN ('hourly', 'daily', 'occasional')),
    aggregation text NOT NULL CHECK (aggregation IN ('sum', 'avg')),
    description text
);

INSERT INTO metric_definition (metric, frequency, aggregation, description) VALUES
    ('step_count',                   'hourly',     'sum', 'Steps'),
    ('walking_running_distance',     'hourly',     'sum', 'Walking + running distance'),
    ('active_energy',                'hourly',     'sum', 'Active energy burned'),
    ('basal_energy_burned',          'hourly',     'sum', 'Resting (basal) energy burned'),
    ('flights_climbed',              'hourly',     'sum', 'Floors climbed'),
    ('apple_exercise_time',          'hourly',     'sum', 'Exercise ring minutes'),
    ('apple_stand_time',             'hourly',     'sum', 'Minutes standing'),
    ('apple_stand_hour',             'hourly',     'sum', 'Stand ring: 1 per hour with a stand'),
    ('mindful_minutes',              'hourly',     'sum', 'Mindfulness minutes'),
    ('physical_effort',              'hourly',     'avg', 'Physical effort (METs-like)'),
    ('heart_rate_variability',       'hourly',     'avg', 'HRV, SDNN'),
    ('heart_rate_variability_rmssd', 'hourly',     'avg', 'HRV, RMSSD'),
    ('walking_step_length',          'hourly',     'avg', 'Average step length'),
    ('stair_speed_up',               'hourly',     'avg', 'Stair ascent speed'),
    ('stair_speed_down',             'hourly',     'avg', 'Stair descent speed'),
    ('resting_heart_rate',           'daily',      'avg', 'Resting heart rate'),
    ('vo2_max',                      'occasional', 'avg', 'Cardio fitness (VO2 max) estimate')
ON CONFLICT (metric) DO UPDATE
    SET frequency = EXCLUDED.frequency,
        aggregation = EXCLUDED.aggregation,
        description = EXCLUDED.description;

-- The app re-sends the last days on every sync: insert with
--   ON CONFLICT (metric, ts, source) DO UPDATE
-- so repeats collapse into one row and a still-filling hour gets its final value.
CREATE TABLE IF NOT EXISTS metric_sample (
    metric      text             NOT NULL,
    ts          timestamptz      NOT NULL,              -- start of the hour (or day)
    qty         double precision NOT NULL,
    unit        text             NOT NULL,              -- as sent, e.g. kJ, count/min
    source      text             NOT NULL DEFAULT '',   -- empty for hourly aggregates
    received_at timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (metric, ts, source)
);

CREATE INDEX IF NOT EXISTS metric_sample_ts_idx ON metric_sample (ts);


-- ---------------------------------------------------------------------------------------
-- Sleep: one row per night, filed under the morning you woke up.
-- ---------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sleep_night (
    night_date   date             NOT NULL,
    source       text             NOT NULL DEFAULT '',
    sleep_start  timestamptz,
    sleep_end    timestamptz,
    in_bed_start timestamptz,
    in_bed_end   timestamptz,
    total_sleep_h double precision,                     -- core + deep + rem
    core_h       double precision,
    deep_h       double precision,
    rem_h        double precision,
    awake_h      double precision,
    asleep_h     double precision,                      -- 0 when stages are recorded
    in_bed_h     double precision,                      -- 0 when stages are recorded
    received_at  timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (night_date, source)
);


-- ---------------------------------------------------------------------------------------
-- Workouts: one row per workout, keyed by the app's UUID.
-- Quantities are converted to the unit in the column name when stored.
-- ---------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS workout (
    workout_id       uuid PRIMARY KEY,
    name             text        NOT NULL,              -- e.g. Traditional Strength Training
    start_ts         timestamptz NOT NULL,
    end_ts           timestamptz NOT NULL,
    duration_s       double precision,
    location         text,                              -- Indoor / Outdoor
    is_indoor        boolean,
    avg_hr           double precision,                  -- bpm
    min_hr           double precision,
    max_hr           double precision,
    active_energy_kj double precision,
    total_energy_kj  double precision,
    intensity        double precision,                  -- kcal/hr·kg
    effort_score     double precision,                  -- Apple's estimated effort, 1-10
    distance_km      double precision,
    speed_kmh        double precision,
    step_cadence     double precision,                  -- steps/min
    temperature_c    double precision,                  -- outdoor weather, even for indoor
    humidity_pct     double precision,
    source_name      text,
    source_id        text,
    -- Nested detail that is rarely queried, kept as sent
    activities       jsonb,
    segments         jsonb,
    splits           jsonb,
    events           jsonb,
    metadata         jsonb,
    received_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (end_ts >= start_ts)
);

CREATE INDEX IF NOT EXISTS workout_start_idx ON workout (start_ts);

-- Minute-by-minute series recorded during a workout
-- (activeEnergy, basalEnergy, stepCount, walkingAndRunningDistance)
CREATE TABLE IF NOT EXISTS workout_sample (
    workout_id uuid             NOT NULL REFERENCES workout ON DELETE CASCADE,
    metric     text             NOT NULL,
    ts         timestamptz      NOT NULL,
    qty        double precision NOT NULL,
    unit       text             NOT NULL,
    PRIMARY KEY (workout_id, metric, ts)
);


-- ---------------------------------------------------------------------------------------
-- Views for analysis
-- ---------------------------------------------------------------------------------------

-- Each metric rolled up to a local day, summed or averaged per metric_definition
CREATE OR REPLACE VIEW daily_metric AS
SELECT local_day(s.ts) AS day,
       s.metric,
       s.unit,
       CASE WHEN d.aggregation = 'sum' THEN sum(s.qty) ELSE avg(s.qty) END AS value,
       count(*) AS samples
FROM metric_sample s
LEFT JOIN metric_definition d USING (metric)
GROUP BY 1, s.metric, s.unit, d.aggregation;

-- Workouts with friendly units; workouts of 0 minutes (the app's "Other" leftovers) flagged
CREATE OR REPLACE VIEW workout_overview AS
SELECT workout_id,
       local_day(start_ts)              AS day,
       name,
       start_ts,
       round((duration_s / 60)::numeric, 1)            AS minutes,
       round(avg_hr::numeric)                          AS avg_hr,
       round(max_hr::numeric)                          AS max_hr,
       round((active_energy_kj / 4.184)::numeric)      AS active_kcal,
       round(distance_km::numeric, 2)                  AS distance_km,
       effort_score,
       coalesce(duration_s, 0) < 60                    AS is_empty
FROM workout;

-- One row per day: activity, recovery, last night's sleep and training
CREATE OR REPLACE VIEW daily_summary AS
WITH m AS (
    SELECT day,
           round(sum(value) FILTER (WHERE metric = 'step_count'))                      AS steps,
           round(sum(value) FILTER (WHERE metric = 'walking_running_distance')::numeric, 2) AS distance_km,
           round(sum(CASE WHEN unit = 'kJ' THEN value / 4.184 ELSE value END)
                 FILTER (WHERE metric = 'active_energy'))                              AS active_kcal,
           round(sum(CASE WHEN unit = 'kJ' THEN value / 4.184 ELSE value END)
                 FILTER (WHERE metric = 'basal_energy_burned'))                        AS basal_kcal,
           round(sum(value) FILTER (WHERE metric = 'apple_exercise_time'))             AS exercise_min,
           round(sum(value) FILTER (WHERE metric = 'apple_stand_hour'))                AS stand_hours,
           round(sum(value) FILTER (WHERE metric = 'flights_climbed'))                 AS floors,
           round(avg(value) FILTER (WHERE metric = 'resting_heart_rate'))              AS resting_hr,
           round(avg(value) FILTER (WHERE metric = 'heart_rate_variability')::numeric, 1) AS hrv_ms,
           round(avg(value) FILTER (WHERE metric = 'vo2_max')::numeric, 1)             AS vo2_max
    FROM daily_metric
    GROUP BY day
),
-- If two devices recorded the same night, keep the longest
s AS (
    SELECT DISTINCT ON (night_date)
           night_date AS day, total_sleep_h, deep_h, rem_h, sleep_start, sleep_end
    FROM sleep_night
    ORDER BY night_date, total_sleep_h DESC NULLS LAST
),
w AS (
    SELECT day,
           count(*)     AS workouts,
           sum(minutes) AS workout_min
    FROM workout_overview
    WHERE NOT is_empty
    GROUP BY day
),
days AS (
    SELECT day FROM m UNION SELECT day FROM s UNION SELECT day FROM w
)
SELECT days.day,
       m.steps, m.distance_km, m.active_kcal, m.basal_kcal, m.exercise_min,
       m.stand_hours, m.floors, m.resting_hr, m.hrv_ms, m.vo2_max,
       round(s.total_sleep_h::numeric, 2) AS sleep_h,
       round(s.deep_h::numeric, 2)        AS deep_sleep_h,
       round(s.rem_h::numeric, 2)         AS rem_sleep_h,
       s.sleep_start, s.sleep_end,
       coalesce(w.workouts, 0)            AS workouts,
       w.workout_min
FROM days
LEFT JOIN m USING (day)
LEFT JOIN s USING (day)
LEFT JOIN w USING (day)
ORDER BY days.day;
