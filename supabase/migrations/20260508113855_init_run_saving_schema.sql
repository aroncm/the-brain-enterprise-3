/*
  # Initialize Run Saving Tool schema

  1. Purpose
    - Establishes the initial schema for the Baseball brAIn Run Saving Tool.
    - Provides a lightweight audit log of enterprise API requests made through
      the edge-function proxy so clubs can review data-readiness history.

  2. New Tables
    - `run_saving_request_log`
      - `id` (uuid, primary key) — unique request identifier.
      - `requested_at` (timestamptz) — when the proxy call was issued.
      - `league` (text) — league scope (`mlb` or `triple_a`).
      - `status` (integer) — HTTP status returned by the upstream source.
      - `latency_ms` (integer) — round-trip latency of the upstream request.
      - `created_at` (timestamptz) — row insertion timestamp.

  3. Security
    - Row Level Security is enabled on `run_saving_request_log`.
    - No public policies are created; only the service role (used by edge
      functions) can write to the table. This keeps the audit log private to
      the club and its enterprise backend.
*/

CREATE TABLE IF NOT EXISTS run_saving_request_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  requested_at timestamptz NOT NULL DEFAULT now(),
  league text NOT NULL DEFAULT 'mlb',
  status integer NOT NULL DEFAULT 0,
  latency_ms integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE run_saving_request_log ENABLE ROW LEVEL SECURITY;
