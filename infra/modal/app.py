from __future__ import annotations

import csv
from collections import defaultdict
import gzip
import html
import json
import math
from http.client import IncompleteRead
from contextlib import contextmanager
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import date, datetime, timezone
import io
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
from zoneinfo import ZoneInfo

import modal
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware


def _resolve_root() -> Path:
    here = Path(__file__).resolve()
    preferred = Path("/root/project")
    if preferred.exists():
        return preferred
    for parent in here.parents:
        if (parent / "abs_stress_test").exists():
            return parent
    return here.parent


ROOT = _resolve_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from abs_stress_test.policy import PolicyConfig
from abs_stress_test.pitching_change import (
    PitchingDecisionThresholds,
    build_degradation_train_holdout_validation,
    build_pitching_preventable_runs_calibration_model,
    build_pitching_decision_snapshots,
    build_pitching_score_calibration_report,
    evaluate_pitching_change_replay,
    score_pitching_preventable_runs_rows,
)
from abs_stress_test.types import (
    ChallengeContext,
    PitchObservation,
    Recommendation,
    RecommendationRequest,
    RecommendationResponse,
)
from infra.modal.ingestion import compute_fingerprint_and_row_count, count_csv_data_rows, fetch_csv_to_path
from infra.modal.savant_abs import (
    collect_abs_challenges_from_statsapi,
    collect_game_pks_from_mlb_schedule,
    enrich_statcast_csv_with_recent_schedule_games,
)
from infra.modal.official_outcomes_metadata import (
    build_official_outcomes_breakdown,
    compute_missed_opportunities,
    compute_run_value_by_handedness,
    derive_official_metadata_public_uri,
    load_official_outcomes_rows,
    normalize_challenge_team,
)
from infra.modal.pitch_facts import (
    augment_audit_payload_with_pitch_facts,
    augment_replay_payload_with_pitch_facts,
    build_pitch_fact_payload,
)
from infra.modal.pitching_artifacts import (
    STATSAPI_CONTEXT_TIMEOUT_SECONDS,
    build_pitching_change_artifacts,
    filter_pitching_audit_summary,
)
from infra.modal.pitcher_fatigue_brief import (
    attach_pitcher_hook_context_to_summary,
    build_pitcher_fatigue_research_summary,
    render_pitcher_fatigue_research_brief,
)
from infra.modal.pitcher_fatigue_pipeline import (
    DEFAULT_PITCHER_FATIGUE_RESEARCH_SEASONS,
    PITCHER_FATIGUE_RESEARCH_BUNDLE_LATEST_KEY,
    PITCHER_FATIGUE_RESEARCH_LATEST_KEY,
    PITCHER_FATIGUE_RESEARCH_PRESENTATION_LATEST_KEY,
    build_pitcher_fatigue_research_bundle_response,
    parse_pitcher_fatigue_research_seasons,
)
from infra.modal.pitcher_fatigue_research import build_pitcher_fatigue_research_export
from infra.modal.pitcher_fatigue_store import (
    default_pitcher_fatigue_refresh_status as shared_default_pitcher_fatigue_refresh_status,
    load_pitcher_fatigue_refresh_status as shared_load_pitcher_fatigue_refresh_status,
    pitcher_fatigue_refresh_status_store,
)
from infra.modal.pitcher_hook_pipeline import (
    DEFAULT_PITCHER_HOOK_DATASET_SEASONS,
    PITCHER_HOOK_DATASET_LATEST_KEY,
    build_pitcher_hook_dataset_payload,
    build_pitcher_hook_dataset_preview_payload,
    parse_pitcher_hook_dataset_seasons,
)
from infra.modal.pitcher_hook_store import (
    default_pitcher_hook_refresh_status as shared_default_pitcher_hook_refresh_status,
    load_pitcher_hook_refresh_status as shared_load_pitcher_hook_refresh_status,
    pitcher_hook_refresh_status_store,
    pitcher_hook_store_get as shared_pitcher_hook_store_get,
    pitcher_hook_store_put as shared_pitcher_hook_store_put,
)
from infra.modal.pitching_support_pipeline import (
    DEFAULT_PITCHING_SUPPORT_GAME_TYPES,
    DEFAULT_PITCHING_SUPPORT_SEASONS,
    PITCHING_SUPPORT_INPUTS_LATEST_KEY,
    build_pitching_support_inputs_payload,
    build_pitching_support_inputs_preview_payload,
    parse_pitching_support_game_types,
    parse_pitching_support_seasons,
)
from infra.modal.pitching_support_store import (
    default_pitching_support_refresh_status as shared_default_pitching_support_refresh_status,
    load_pitching_support_refresh_status as shared_load_pitching_support_refresh_status,
    pitching_support_refresh_status_store,
    pitching_support_store_get as shared_pitching_support_store_get,
    pitching_support_store_put as shared_pitching_support_store_put,
)
from infra.modal.pitcher_fatigue_sig_pack import (
    build_pitcher_fatigue_sig_presentation,
    render_pitcher_fatigue_sig_memo,
)
from infra.modal.pitching_postgame import build_pitching_postgame_report
from infra.modal.pitching_context import (
    build_pitching_game_context,
    discover_pitching_active_rosters_csv_path,
    discover_pitching_backfill_csv_path,
    discover_pitching_bullpen_roles_csv_path,
    discover_pitching_player_status_csv_path,
    discover_pitching_transactions_csv_path,
)
from infra.modal.minor_league_pitching import export_triple_a_pitching_csv
from infra.modal.pitching_store import (
    DEFAULT_PITCHING_LEAGUE,
    TRIPLE_A_PITCHING_LEAGUE,
    default_pitching_refresh_status as shared_default_pitching_refresh_status,
    load_pitching_refresh_status as shared_load_pitching_refresh_status,
    normalize_pitching_league as shared_normalize_pitching_league,
    normalize_pitching_replay_payload as shared_normalize_pitching_replay_payload,
    pitching_refresh_status_key as shared_pitching_refresh_status_key,
    pitching_refresh_status_store,
    pitching_store_get as shared_pitching_store_get,
    pitching_store_key as shared_pitching_store_key,
    pitching_store_put as shared_pitching_store_put,
)
from infra.modal.recommend_service import RecommendService
from infra.modal.replay_audit import build_actual_vs_policy_summary
from infra.modal.replay_refresh import (
    build_replay_dataset,
    normalize_replay_scope,
    read_replay_catalog,
    read_replay_refresh_meta,
    replay_output_path,
    replay_scope_tag,
    write_replay_catalog,
    write_replay_refresh_meta,
)
from infra.modal.replay_share import (
    build_pitching_replay_share_url,
    issue_pitching_replay_share_grant,
    get_pitching_replay_share_grant,
    is_pitching_replay_share_active,
    mask_email,
    normalize_email,
    put_pitching_replay_share_grant,
)
from infra.modal.schemas import RecommendationRequestModel
from infra.modal.settings import Settings, load_settings
from infra.modal.stress_artifacts import (
    ARTIFACT_MODE_FAST_BASE,
    ARTIFACT_MODE_FULL_MATRIX,
    build_model_version_row,
    build_stress_test_row,
    generate_model_evaluation_artifact,
    generate_stress_test_artifacts,
)
from infra.modal.supabase_repo import SupabaseRepo


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("infra/modal/requirements.txt")
    .add_local_dir("abs_stress_test", remote_path="/root/project/abs_stress_test")
    .add_local_dir("infra", remote_path="/root/project/infra")
    .add_local_dir("data", remote_path="/root/project/data")
    .add_local_dir("data_templates", remote_path="/root/project/data_templates")
    .add_local_dir("scripts", remote_path="/root/project/scripts")
    .add_local_dir("outputs", remote_path="/root/project/outputs")
)
app = modal.App("abs-challenge-api-tuned")
stress_status_store = modal.Dict.from_name("abs-stress-status", create_if_missing=True)
model_evaluation_status_store = modal.Dict.from_name("abs-model-evaluation-status", create_if_missing=True)
replay_audit_summary_store = modal.Dict.from_name("abs-replay-audit-summary", create_if_missing=True)
replay_catalog_store = modal.Dict.from_name("abs-replay-catalog", create_if_missing=True)
data_sync_store = modal.Dict.from_name("abs-data-sync", create_if_missing=True)
statsapi_refresh_store = modal.Dict.from_name("abs-statsapi-refresh-status", create_if_missing=True)
live_signal_game_store = modal.Dict.from_name("abs-live-signal-games", create_if_missing=True)
pitching_recap_settings_store = modal.Dict.from_name("abs-pitching-recap-settings", create_if_missing=True)
shared_pitcher_intel_settings_store = modal.Dict.from_name("abs-pitcher-intel-recap", create_if_missing=True)
pitching_calibration_status_store = modal.Dict.from_name("abs-pitching-calibration-status", create_if_missing=True)


def _pitching_store_put(key: str, value: Any) -> None:
    """Store a pitching artifact as gzip-compressed JSON to stay within Modal Dict size limits."""
    shared_pitching_store_put(key, value)


def _pitching_store_get(key: str) -> Any:
    """Retrieve a pitching artifact, decompressing if needed (handles legacy uncompressed entries)."""
    return shared_pitching_store_get(key)


def _pitcher_hook_store_put(key: str, value: Any) -> None:
    shared_pitcher_hook_store_put(key, value)


def _pitcher_hook_store_get(key: str) -> Any:
    return shared_pitcher_hook_store_get(key)


def _latest_pitcher_hook_dataset_summary() -> dict[str, Any] | None:
    payload = _pitcher_hook_store_get(PITCHER_HOOK_DATASET_LATEST_KEY)
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None
    return dict(summary)


def _pitching_support_store_put(key: str, value: Any) -> None:
    shared_pitching_support_store_put(key, value)


def _pitching_support_store_get(key: str) -> Any:
    return shared_pitching_support_store_get(key)


def _live_signal_store_get(store: modal.Dict, key: str, default: Any = None) -> Any:
    try:
        raw = store.get(key)
        if raw is None:
            return default
        if isinstance(raw, (bytes, bytearray)):
            return json.loads(gzip.decompress(raw))
        return raw
    except Exception:
        return default


def _modal_dict_get(store: modal.Dict, key: str, default: Any = None) -> Any:
    try:
        value = store.get(key)
    except Exception:
        return default
    if isinstance(value, (bytes, bytearray)):
        try:
            return json.loads(gzip.decompress(value))
        except Exception:
            return default
    return default if value is None else value


def _normalize_pitching_recap_team(value: Any) -> str | None:
    token = "".join(ch for ch in str(value or "").upper() if ch.isalpha())[:4]
    return token if len(token) >= 2 else None


def _normalize_pitching_recap_email_provider(value: Any) -> str:
    provider = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if provider == "smtp":
        return "smtp"
    return "resend"


def _smtp_port_value(value: Any) -> int:
    try:
        port = int(value)
    except Exception:
        return 465
    if port <= 0 or port > 65535:
        return 465
    return port


def _normalize_recipients(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(part or "").strip() for part in value]
    else:
        candidates = []

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        email = normalize_email(raw)
        if not email or email in seen:
            continue
        seen.add(email)
        normalized.append(email)
    return normalized


BUILD_ID = "2026-03-02-abs-tune-v1"
MLB_STATS_API = "https://statsapi.mlb.com"
MAX_ACTUAL_CHALLENGE_DENSITY = 0.25
MAX_ACTUAL_CHALLENGES_PER_GAME = 20
REPLAY_PREWARM_GAME_LIMIT = 8
FAST_BASE_MAX_SIMS = 24
BRAIN_APP_BASE_URL = os.getenv("BRAIN_APP_BASE_URL", "https://getbaseballbrain.com").strip().rstrip("/")
CANONICAL_RUN_PREVENTION_APP_BASE_URL = "https://baseballbrain.club"
RUN_PREVENTION_APP_BASE_URL = os.getenv(
    "RUN_PREVENTION_APP_BASE_URL",
    CANONICAL_RUN_PREVENTION_APP_BASE_URL,
).strip().rstrip("/")
if RUN_PREVENTION_APP_BASE_URL.endswith(".bolt.host") or RUN_PREVENTION_APP_BASE_URL == BRAIN_APP_BASE_URL:
    RUN_PREVENTION_APP_BASE_URL = CANONICAL_RUN_PREVENTION_APP_BASE_URL
OFFICIAL_OUTCOMES_LOCAL_METADATA_PATHS = [
    "/root/project/data/production/statcast_merged_with_statsapi_backfill.csv",
    "/root/project/data/production/statcast_merged_backfill.csv",
    "/root/project/data/production/statcast_export.csv",
]


class AppState:
    def __init__(self) -> None:
        self.latest_result: dict[str, Any] | None = None
        self.latest_memo: str = ""
        self.latest_memo_assumption_warnings: list[str] = []
        self.last_retrain_at: str | None = None
        self.last_stress_test_at: str | None = None
        self.last_ingest_at: str | None = None
        self.backfill_in_progress: bool = False
        self.recompute_futures: dict[str, Future[dict[str, Any]]] = {}
        self.recompute_status: dict[str, dict[str, Any]] = {}
        self.model_evaluation_status: dict[str, Any] = {}
        self.replay_services: dict[str, RecommendService] = {}
        self.replay_service_paths: dict[str, str] = {}
        self.replay_games_cache: dict[str, list[dict[str, Any]]] = {}
        self.replay_payload_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self.replay_game_stats_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self.replay_catalog_cache: dict[str, list[dict[str, Any]]] = {}
        self.replay_dataset_stats_cache: dict[str, dict[str, Any]] = {}
        self.replay_refresh_meta: dict[str, Any] = {}
        self.official_challenge_counts_by_game: dict[str, int] | None = None
        self.pitching_summary: dict[str, dict[str, Any]] = {}
        self.pitching_games_cache: dict[str, list[dict[str, Any]]] = {}
        self.pitching_replay_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self.pitching_audit_cache: dict[str, dict[str, Any]] = {}
        self.pitching_refresh_status: dict[str, dict[str, Any]] = {}
        self.pitching_official_pitch_facts_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self.pitching_official_boxscore_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self.pitching_official_game_score_cache: dict[str, dict[str, dict[str, Any]]] = {}


STATE = AppState()


def _replay_audit_summary_key(scope: str) -> str:
    return f"scope:{scope}"


def _set_replay_audit_summary(scope: str, payload: dict[str, Any]) -> None:
    try:
        replay_audit_summary_store.put(_replay_audit_summary_key(scope), payload)
    except Exception as exc:
        print(f"[abs-modal] failed to persist replay audit summary for scope={scope}: {exc}")


def _get_replay_audit_summary(scope: str) -> dict[str, Any] | None:
    try:
        stored = replay_audit_summary_store.get(_replay_audit_summary_key(scope))
    except KeyError:
        return None
    except Exception as exc:
        print(f"[abs-modal] failed to load replay audit summary for scope={scope}: {exc}")
        return None
    return dict(stored) if isinstance(stored, dict) else None


def _normalize_pitching_league(league: str | None) -> str:
    return shared_normalize_pitching_league(league)


def _pitching_store_key(kind: str, game_id: str | None = None, *, league: str = DEFAULT_PITCHING_LEAGUE) -> str:
    return shared_pitching_store_key(kind, game_id, league=league)


def _default_pitching_refresh_status() -> dict[str, Any]:
    return shared_default_pitching_refresh_status()


def _default_pitcher_hook_refresh_status() -> dict[str, Any]:
    return shared_default_pitcher_hook_refresh_status()


def _default_pitching_support_refresh_status() -> dict[str, Any]:
    return shared_default_pitching_support_refresh_status()


def _persist_pitching_refresh_status(snapshot: dict[str, Any], *, league: str = DEFAULT_PITCHING_LEAGUE) -> None:
    try:
        pitching_refresh_status_store.put(shared_pitching_refresh_status_key(league=league), snapshot)
    except Exception as exc:
        print(f"[abs-modal] failed to persist pitching refresh status: {exc}")


def _load_pitching_refresh_status(*, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any]:
    return shared_load_pitching_refresh_status(league=league)


def _pitching_calibration_status_key(*, season: int) -> str:
    return f"season:{int(season)}"


def _pitching_calibration_latest_key(*, season: int) -> str:
    return f"pitching_calibration:{int(season)}:latest"


def _pitching_preventable_model_status_key(*, season: int) -> str:
    return f"preventable_runs_model:{int(season)}"


def _pitching_preventable_model_latest_key(*, season: int) -> str:
    return f"pitching_preventable_runs_model:{int(season)}:latest"


def _default_pitching_calibration_status() -> dict[str, Any]:
    return {
        "status": "idle",
        "active": False,
        "requested_at": None,
        "started_at": None,
        "completed_at": None,
        "generated_at": None,
        "season": None,
        "start_date": None,
        "end_date": None,
        "game_type": None,
        "source_row_count": None,
        "filtered_row_count": None,
        "game_count": None,
        "snapshot_count": None,
        "calibration_row_count": None,
        "artifact_urls": {},
        "last_error": None,
    }


def _default_pitching_preventable_model_status() -> dict[str, Any]:
    return {
        "status": "idle",
        "active": False,
        "requested_at": None,
        "started_at": None,
        "completed_at": None,
        "generated_at": None,
        "season": None,
        "training_start_date": None,
        "training_end_date": None,
        "holdout_start_date": None,
        "holdout_end_date": None,
        "game_type": None,
        "source_row_count": None,
        "training_filtered_row_count": None,
        "holdout_filtered_row_count": None,
        "training_game_count": None,
        "holdout_game_count": None,
        "training_snapshot_count": None,
        "holdout_snapshot_count": None,
        "training_calibration_row_count": None,
        "holdout_calibration_row_count": None,
        "artifact_urls": {},
        "last_error": None,
    }


def _persist_pitching_calibration_status(snapshot: dict[str, Any], *, season: int) -> None:
    try:
        pitching_calibration_status_store.put(_pitching_calibration_status_key(season=season), snapshot)
    except Exception as exc:
        print(f"[abs-modal] failed to persist pitching calibration status: {exc}")


def _load_pitching_calibration_status(*, season: int) -> dict[str, Any]:
    try:
        payload = pitching_calibration_status_store.get(_pitching_calibration_status_key(season=season))
        if isinstance(payload, dict):
            merged = _default_pitching_calibration_status()
            merged.update(payload)
            return merged
    except Exception:
        pass
    status = _default_pitching_calibration_status()
    status["season"] = int(season)
    return status


def _persist_pitching_preventable_model_status(snapshot: dict[str, Any], *, season: int) -> None:
    try:
        pitching_calibration_status_store.put(_pitching_preventable_model_status_key(season=season), snapshot)
    except Exception as exc:
        print(f"[abs-modal] failed to persist pitching preventable-runs model status: {exc}")


def _load_pitching_preventable_model_status(*, season: int) -> dict[str, Any]:
    try:
        payload = pitching_calibration_status_store.get(_pitching_preventable_model_status_key(season=season))
        if isinstance(payload, dict):
            merged = _default_pitching_preventable_model_status()
            merged.update(payload)
            return merged
    except Exception:
        pass
    status = _default_pitching_preventable_model_status()
    status["season"] = int(season)
    return status


def _persist_pitcher_hook_refresh_status(snapshot: dict[str, Any]) -> None:
    try:
        pitcher_hook_refresh_status_store.put("pitcher_hook_refresh_status", snapshot)
    except Exception as exc:
        print(f"[abs-modal] failed to persist pitcher hook refresh status: {exc}")


def _load_pitcher_hook_refresh_status() -> dict[str, Any]:
    return shared_load_pitcher_hook_refresh_status()


def _persist_pitching_support_refresh_status(snapshot: dict[str, Any]) -> None:
    try:
        pitching_support_refresh_status_store.put("pitching_support_refresh_status", snapshot)
    except Exception as exc:
        print(f"[abs-modal] failed to persist pitching support refresh status: {exc}")


def _load_pitching_support_refresh_status() -> dict[str, Any]:
    return shared_load_pitching_support_refresh_status()


def _default_pitcher_fatigue_refresh_status() -> dict[str, Any]:
    return shared_default_pitcher_fatigue_refresh_status()


def _persist_pitcher_fatigue_refresh_status(snapshot: dict[str, Any]) -> None:
    try:
        pitcher_fatigue_refresh_status_store.put("pitcher_fatigue_refresh_status", snapshot)
    except Exception as exc:
        print(f"[abs-modal] failed to persist pitcher fatigue refresh status: {exc}")


def _load_pitcher_fatigue_refresh_status() -> dict[str, Any]:
    return shared_load_pitcher_fatigue_refresh_status()


def _refresh_and_persist_pitcher_hook_dataset(
    settings: Settings,
    *,
    requested_at: str | None = None,
    seasons: str = DEFAULT_PITCHER_HOOK_DATASET_SEASONS,
    starter_target: int = 90,
    reliever_target: int = 150,
    min_pitch_count: int | None = None,
    active_rosters_csv_path_override: str | None = None,
    bullpen_roles_csv_path_override: str | None = None,
) -> dict[str, Any]:
    started_at = _utc_now_iso()
    running = _default_pitcher_hook_refresh_status()
    resolved_min_pitch_count = int(min_pitch_count or settings.abs_pitching_min_pitch_count)
    running.update(
        {
            "status": "running",
            "active": True,
            "requested_at": requested_at or started_at,
            "started_at": started_at,
            "seasons": list(parse_pitcher_hook_dataset_seasons(seasons)),
            "starter_target": int(starter_target),
            "reliever_target": int(reliever_target),
            "min_pitch_count": resolved_min_pitch_count,
        }
    )
    _persist_pitcher_hook_refresh_status(running)
    try:
        dataset, season_values = build_pitcher_hook_dataset_payload(
            settings,
            seasons=seasons,
            starter_target=starter_target,
            reliever_target=reliever_target,
            min_pitch_count=resolved_min_pitch_count,
            active_rosters_csv_path_override=active_rosters_csv_path_override,
            bullpen_roles_csv_path_override=bullpen_roles_csv_path_override,
            root=str(ROOT),
        )
        latest_payload = build_pitcher_hook_dataset_preview_payload(dataset)
        _pitcher_hook_store_put(PITCHER_HOOK_DATASET_LATEST_KEY, latest_payload)
        completed = _default_pitcher_hook_refresh_status()
        completed.update(
            {
                "status": "completed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "generated_at": (latest_payload.get("summary") or {}).get("generated_at"),
                "decision_state_count": (latest_payload.get("summary") or {}).get("decision_state_count"),
                "candidate_row_count": (latest_payload.get("summary") or {}).get("candidate_row_count"),
                "seasons": list(season_values),
                "starter_target": int(starter_target),
                "reliever_target": int(reliever_target),
                "min_pitch_count": resolved_min_pitch_count,
            }
        )
        _persist_pitcher_hook_refresh_status(completed)
        return completed
    except Exception as exc:
        failed = _default_pitcher_hook_refresh_status()
        failed.update(
            {
                "status": "failed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "seasons": running.get("seasons"),
                "starter_target": int(starter_target),
                "reliever_target": int(reliever_target),
                "min_pitch_count": resolved_min_pitch_count,
                "last_error": str(exc),
            }
        )
        _persist_pitcher_hook_refresh_status(failed)
        raise


def _build_pitcher_hook_refresh_response(snapshot: dict[str, Any]) -> dict[str, Any]:
    latest_payload = _pitcher_hook_store_get(PITCHER_HOOK_DATASET_LATEST_KEY)
    latest_summary = dict(latest_payload.get("summary") or {}) if isinstance(latest_payload, dict) else {}
    status = str(snapshot.get("status") or "idle")
    return {
        "status": "accepted" if status == "running" else status,
        "pitcher_hook_last_refresh_status": status,
        "requested_at": snapshot.get("requested_at"),
        "started_at": snapshot.get("started_at"),
        "completed_at": snapshot.get("completed_at"),
        "generated_at": latest_summary.get("generated_at") or snapshot.get("generated_at"),
        "decision_state_count": latest_summary.get("decision_state_count") or snapshot.get("decision_state_count"),
        "candidate_row_count": latest_summary.get("candidate_row_count") or snapshot.get("candidate_row_count"),
        "seasons": snapshot.get("seasons") or latest_summary.get("seasons"),
        "starter_target": snapshot.get("starter_target"),
        "reliever_target": snapshot.get("reliever_target"),
        "min_pitch_count": snapshot.get("min_pitch_count"),
        "last_error": snapshot.get("last_error"),
    }


def _refresh_and_persist_pitching_support_inputs(
    settings: Settings,
    *,
    requested_at: str | None = None,
    seasons: str = DEFAULT_PITCHING_SUPPORT_SEASONS,
    game_types: str = DEFAULT_PITCHING_SUPPORT_GAME_TYPES,
    timeout_seconds: float = 20.0,
    upload_outputs: bool = True,
    return_payload: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    started_at = _utc_now_iso()
    running = _default_pitching_support_refresh_status()
    running.update(
        {
            "status": "running",
            "active": True,
            "requested_at": requested_at or started_at,
            "started_at": started_at,
            "seasons": list(parse_pitching_support_seasons(seasons)),
            "game_types": list(parse_pitching_support_game_types(game_types)),
            "timeout_seconds": float(timeout_seconds),
        }
    )
    _persist_pitching_support_refresh_status(running)
    try:
        payload, season_values, game_type_values = build_pitching_support_inputs_payload(
            settings,
            seasons=seasons,
            game_types=game_types,
            timeout_seconds=timeout_seconds,
            upload_outputs=upload_outputs,
            root=str(ROOT),
        )
        latest_payload = build_pitching_support_inputs_preview_payload(payload)
        _pitching_support_store_put(PITCHING_SUPPORT_INPUTS_LATEST_KEY, latest_payload)
        summary = dict(payload.get("summary") or {})
        completed = _default_pitching_support_refresh_status()
        completed.update(
            {
                "status": "completed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "generated_at": summary.get("generated_at"),
                "seasons": list(season_values),
                "game_types": list(game_type_values),
                "timeout_seconds": float(timeout_seconds),
                "game_count": summary.get("game_count"),
                "active_roster_row_count": summary.get("active_roster_row_count"),
                "bullpen_role_row_count": summary.get("bullpen_role_row_count"),
                "active_rosters_upload_status": (summary.get("active_rosters_upload") or {}).get("status"),
                "bullpen_roles_upload_status": (summary.get("bullpen_roles_upload") or {}).get("status"),
            }
        )
        _persist_pitching_support_refresh_status(completed)
        if return_payload:
            return completed, payload
        return completed
    except Exception as exc:
        failed = _default_pitching_support_refresh_status()
        failed.update(
            {
                "status": "failed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "seasons": running.get("seasons"),
                "game_types": running.get("game_types"),
                "timeout_seconds": float(timeout_seconds),
                "last_error": str(exc),
            }
        )
        _persist_pitching_support_refresh_status(failed)
        raise


def _build_pitching_support_refresh_response(snapshot: dict[str, Any]) -> dict[str, Any]:
    latest_payload = _pitching_support_store_get(PITCHING_SUPPORT_INPUTS_LATEST_KEY)
    latest_summary = dict(latest_payload.get("summary") or {}) if isinstance(latest_payload, dict) else {}
    status = str(snapshot.get("status") or "idle")
    return {
        "status": "accepted" if status == "running" else status,
        "pitching_support_last_refresh_status": status,
        "requested_at": snapshot.get("requested_at"),
        "started_at": snapshot.get("started_at"),
        "completed_at": snapshot.get("completed_at"),
        "generated_at": latest_summary.get("generated_at") or snapshot.get("generated_at"),
        "seasons": snapshot.get("seasons") or latest_summary.get("seasons"),
        "game_types": snapshot.get("game_types") or latest_summary.get("game_types"),
        "timeout_seconds": snapshot.get("timeout_seconds"),
        "game_count": latest_summary.get("game_count") or snapshot.get("game_count"),
        "active_roster_row_count": latest_summary.get("active_roster_row_count") or snapshot.get("active_roster_row_count"),
        "bullpen_role_row_count": latest_summary.get("bullpen_role_row_count") or snapshot.get("bullpen_role_row_count"),
        "active_rosters_upload_status": (
            latest_summary.get("active_rosters_upload", {}).get("status")
            if isinstance(latest_summary.get("active_rosters_upload"), dict)
            else snapshot.get("active_rosters_upload_status")
        ),
        "bullpen_roles_upload_status": (
            latest_summary.get("bullpen_roles_upload", {}).get("status")
            if isinstance(latest_summary.get("bullpen_roles_upload"), dict)
            else snapshot.get("bullpen_roles_upload_status")
        ),
        "last_error": snapshot.get("last_error"),
    }


def _refresh_and_persist_pitcher_fatigue_research(
    settings: Settings,
    *,
    requested_at: str | None = None,
    seasons: str = DEFAULT_PITCHER_FATIGUE_RESEARCH_SEASONS,
    starter_target: int = 90,
    reliever_target: int = 150,
    include_starter_signal_context: bool = True,
    include_charts: bool = True,
) -> dict[str, Any]:
    started_at = _utc_now_iso()
    hook_dataset_summary = _latest_pitcher_hook_dataset_summary()
    running = _default_pitcher_fatigue_refresh_status()
    running.update(
        {
            "status": "running",
            "active": True,
            "requested_at": requested_at or started_at,
            "started_at": started_at,
            "seasons": list(parse_pitcher_fatigue_research_seasons(seasons)),
            "starter_target": int(starter_target),
            "reliever_target": int(reliever_target),
            "include_starter_signal_context": bool(include_starter_signal_context),
        }
    )
    _persist_pitcher_fatigue_refresh_status(running)
    try:
        bundle = build_pitcher_fatigue_research_bundle_response(
            settings,
            seasons=seasons,
            starter_target=starter_target,
            reliever_target=reliever_target,
            include_starter_signal_context=include_starter_signal_context,
            include_charts=include_charts,
            hook_dataset_summary=hook_dataset_summary,
            root=str(ROOT),
        )
        analysis_payload = {
            "query": dict(bundle.get("query") or {}),
            "export_summary": dict(bundle.get("export_summary") or {}),
            "analysis": dict(bundle.get("analysis") or {}),
            "brief_markdown": str(bundle.get("brief_markdown") or ""),
            "truth_feeds": dict(bundle.get("truth_feeds") or {}),
        }
        presentation_payload = {
            "query": dict(bundle.get("query") or {}),
            "export_summary": dict(bundle.get("export_summary") or {}),
            "analysis": dict(bundle.get("analysis") or {}),
            "presentation": dict(bundle.get("presentation") or {}),
            "memo_markdown": str(bundle.get("memo_markdown") or ""),
            "truth_feeds": dict(bundle.get("truth_feeds") or {}),
        }
        _pitching_store_put(PITCHER_FATIGUE_RESEARCH_LATEST_KEY, analysis_payload)
        _pitching_store_put(PITCHER_FATIGUE_RESEARCH_PRESENTATION_LATEST_KEY, presentation_payload)
        _pitching_store_put(PITCHER_FATIGUE_RESEARCH_BUNDLE_LATEST_KEY, bundle)
        export_summary = dict(bundle.get("export_summary") or {})
        chart_manifest = bundle.get("chart_manifest") if isinstance(bundle.get("chart_manifest"), dict) else {}
        truth_feeds = dict(bundle.get("truth_feeds") or {})
        manager_feed = truth_feeds.get("manager_game_log") if isinstance(truth_feeds.get("manager_game_log"), dict) else {}
        completed = _default_pitcher_fatigue_refresh_status()
        completed.update(
            {
                "status": "completed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "generated_at": export_summary.get("generated_at") or bundle.get("generated_at"),
                "seasons": list((bundle.get("query") or {}).get("seasons") or parse_pitcher_fatigue_research_seasons(seasons)),
                "starter_target": int(starter_target),
                "reliever_target": int(reliever_target),
                "include_starter_signal_context": bool(include_starter_signal_context),
                "analysis_generated": True,
                "presentation_generated": True,
                "bundle_generated": True,
                "chart_count": chart_manifest.get("generated_chart_count"),
                "source_transaction_csv": export_summary.get("source_transaction_csv"),
                "source_player_status_csv": export_summary.get("source_player_status_csv"),
                "source_manager_game_log_csv": manager_feed.get("resolved_path"),
            }
        )
        _persist_pitcher_fatigue_refresh_status(completed)
        return completed
    except Exception as exc:
        failed = _default_pitcher_fatigue_refresh_status()
        failed.update(
            {
                "status": "failed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "seasons": running.get("seasons"),
                "starter_target": int(starter_target),
                "reliever_target": int(reliever_target),
                "include_starter_signal_context": bool(include_starter_signal_context),
                "last_error": str(exc),
            }
        )
        _persist_pitcher_fatigue_refresh_status(failed)
        raise


def _build_pitcher_fatigue_refresh_response(snapshot: dict[str, Any]) -> dict[str, Any]:
    latest_bundle = _pitching_store_get(PITCHER_FATIGUE_RESEARCH_BUNDLE_LATEST_KEY)
    latest_summary = dict(latest_bundle.get("export_summary") or {}) if isinstance(latest_bundle, dict) else {}
    latest_query = dict(latest_bundle.get("query") or {}) if isinstance(latest_bundle, dict) else {}
    latest_generated_at = latest_bundle.get("generated_at") if isinstance(latest_bundle, dict) else None
    latest_chart_manifest = (
        dict(latest_bundle.get("chart_manifest") or {})
        if isinstance(latest_bundle, dict) and isinstance(latest_bundle.get("chart_manifest"), dict)
        else {}
    )
    latest_truth_feeds = dict(latest_bundle.get("truth_feeds") or {}) if isinstance(latest_bundle, dict) else {}
    manager_feed = latest_truth_feeds.get("manager_game_log") if isinstance(latest_truth_feeds.get("manager_game_log"), dict) else {}
    status = str(snapshot.get("status") or "idle")
    return {
        "status": "accepted" if status == "running" else status,
        "pitcher_fatigue_last_refresh_status": status,
        "requested_at": snapshot.get("requested_at"),
        "started_at": snapshot.get("started_at"),
        "completed_at": snapshot.get("completed_at"),
        "generated_at": latest_summary.get("generated_at") or latest_generated_at or snapshot.get("generated_at"),
        "seasons": snapshot.get("seasons") or latest_query.get("seasons"),
        "starter_target": snapshot.get("starter_target") or latest_query.get("starter_target"),
        "reliever_target": snapshot.get("reliever_target") or latest_query.get("reliever_target"),
        "include_starter_signal_context": snapshot.get("include_starter_signal_context"),
        "chart_count": latest_chart_manifest.get("generated_chart_count") or snapshot.get("chart_count"),
        "source_transaction_csv": latest_summary.get("source_transaction_csv") or snapshot.get("source_transaction_csv"),
        "source_player_status_csv": latest_summary.get("source_player_status_csv") or snapshot.get("source_player_status_csv"),
        "source_manager_game_log_csv": manager_feed.get("resolved_path") or snapshot.get("source_manager_game_log_csv"),
        "last_error": snapshot.get("last_error"),
    }


def _invalidate_pitching_caches(*, league: str = DEFAULT_PITCHING_LEAGUE) -> None:
    STATE.pitching_summary.pop(league, None)
    STATE.pitching_games_cache.pop(league, None)
    STATE.pitching_replay_cache.pop(league, None)
    STATE.pitching_audit_cache.pop(league, None)
    STATE.pitching_official_pitch_facts_cache.pop(league, None)
    STATE.pitching_official_boxscore_cache.pop(league, None)


def _refresh_pitching_caches_if_stale(*, league: str = DEFAULT_PITCHING_LEAGUE) -> None:
    cached_summary = STATE.pitching_summary.get(league) if isinstance(STATE.pitching_summary.get(league), dict) else None
    if not cached_summary:
        return
    status = _load_pitching_refresh_status(league=league)
    if str(status.get("status") or "") != "completed":
        return
    cached_generated_at = _parse_iso_datetime(str(cached_summary.get("generated_at") or ""))
    latest_generated_at = _parse_iso_datetime(str(status.get("generated_at") or ""))
    if latest_generated_at is None:
        return
    if cached_generated_at is None or latest_generated_at > cached_generated_at:
        _invalidate_pitching_caches(league=league)


def _set_pitching_artifacts(payload: dict[str, Any], *, league: str = DEFAULT_PITCHING_LEAGUE) -> None:
    summary = dict(payload.get("summary") or {})
    games = [dict(item) for item in payload.get("games") or [] if isinstance(item, dict)]
    audit = dict(payload.get("audit") or {})
    replays = {
        str(key): _normalize_pitching_replay_payload(dict(value))
        for key, value in dict(payload.get("replays") or {}).items()
        if isinstance(value, dict)
    }
    try:
        _pitching_store_put(_pitching_store_key("summary", league=league), summary)
        _pitching_store_put(_pitching_store_key("games", league=league), games)
        _pitching_store_put(_pitching_store_key("audit", league=league), audit)
        for game_id, replay_payload in replays.items():
            _pitching_store_put(_pitching_store_key("replay", game_id, league=league), replay_payload)
    except Exception as exc:
        print(f"[abs-modal] failed to persist pitching artifacts: {exc}")
        raise
    STATE.pitching_summary[league] = summary
    STATE.pitching_games_cache[league] = games
    STATE.pitching_audit_cache[league] = audit
    STATE.pitching_replay_cache[league] = replays


def _get_pitching_summary(*, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any] | None:
    _refresh_pitching_caches_if_stale(league=league)
    cached = STATE.pitching_summary.get(league)
    if isinstance(cached, dict) and cached:
        return dict(cached)
    try:
        payload = _pitching_store_get(_pitching_store_key("summary", league=league))
    except Exception:
        payload = None
    if isinstance(payload, dict):
        STATE.pitching_summary[league] = dict(payload)
        return dict(payload)
    return None


def _get_pitching_games(*, league: str = DEFAULT_PITCHING_LEAGUE) -> list[dict[str, Any]]:
    _refresh_pitching_caches_if_stale(league=league)
    cached = STATE.pitching_games_cache.get(league)
    if isinstance(cached, list) and cached:
        return [dict(item) for item in cached]
    try:
        payload = _pitching_store_get(_pitching_store_key("games", league=league))
    except Exception:
        payload = None
    games = [dict(item) for item in payload] if isinstance(payload, list) else []
    if games:
        STATE.pitching_games_cache[league] = games
    return games


def _get_pitching_audit(*, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any] | None:
    _refresh_pitching_caches_if_stale(league=league)
    cached = STATE.pitching_audit_cache.get(league)
    if isinstance(cached, dict) and cached:
        return dict(cached)
    try:
        payload = _pitching_store_get(_pitching_store_key("audit", league=league))
    except Exception:
        payload = None
    if isinstance(payload, dict):
        STATE.pitching_audit_cache[league] = dict(payload)
        return dict(payload)
    return None


def _normalize_pitching_replay_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return shared_normalize_pitching_replay_payload(payload)


def _fetch_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    request = UrlRequest(url, headers={"User-Agent": "the-brain/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _pitching_source_status(
    *,
    value: Any = None,
    source: str,
    status: str,
    notes: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "available": value is not None and value != "",
        "source": source,
        "status": status,
    }
    if notes:
        payload["notes"] = notes
    return payload


def _augment_pitching_replay_source_status(
    payload: dict[str, Any],
    *,
    has_pitch_facts: bool,
) -> dict[str, Any]:
    """Attach field-level lineage to replay entries without changing model values."""
    if not isinstance(payload, dict):
        return dict(payload)
    normalized = dict(payload)
    entry_rows: list[Any] = []
    for raw_entry in normalized.get("entries") or []:
        if not isinstance(raw_entry, dict):
            entry_rows.append(raw_entry)
            continue
        entry = dict(raw_entry)
        snapshot = dict(entry.get("snapshot") or {})
        state = dict(snapshot.get("starter_state") or {})
        official_pitch_count = state.get("official_pitch_count_in_game")
        pitch_fact_source = "statsapi_live_game_feed_pitch_facts" if has_pitch_facts else "pitching_replay_artifact"
        pitch_count_source = (
            "statsapi_live_game_feed_pitch_facts"
            if official_pitch_count is not None
            else "pitching_replay_artifact"
        )
        snapshot["sourceStatus"] = {
            "pitch": _pitching_source_status(value=snapshot.get("pitch_id"), source="pitching_replay_artifact", status="available"),
            "pitcher": _pitching_source_status(value=snapshot.get("pitcher_id"), source="pitching_replay_artifact", status="available"),
            "gameState": _pitching_source_status(value=snapshot.get("inning"), source=pitch_fact_source, status="available"),
            "score": _pitching_source_status(value=snapshot.get("home_score"), source=pitch_fact_source, status="available"),
            "baseOutState": _pitching_source_status(value=snapshot.get("base_state"), source=pitch_fact_source, status="available"),
            "pitchType": _pitching_source_status(value=snapshot.get("pitch_type"), source="mlb_live_feed_pitch_event", status="available" if snapshot.get("pitch_type") else "unavailable"),
            "velocity": _pitching_source_status(value=snapshot.get("release_speed"), source="statcast_tracking", status="available" if snapshot.get("release_speed") is not None else "unavailable"),
            "plateLocation": _pitching_source_status(value=snapshot.get("px"), source="statcast_tracking", status="available" if snapshot.get("px") is not None and snapshot.get("pz") is not None else "unavailable"),
            "leverage": _pitching_source_status(value=snapshot.get("leverage_index"), source="base_out_score_leverage_model", status="model"),
            "actualChange": _pitching_source_status(
                value=snapshot.get("actual_change_pitch_id") or snapshot.get("actual_change_after_pitches"),
                source=pitch_count_source,
                status="available" if snapshot.get("actual_change_pitch_id") or snapshot.get("actual_change_after_pitches") is not None else "unavailable",
                notes="Observed replacement timing from replay; official pitch counts are used when pitch facts are attached.",
            ),
        }
        state["sourceStatus"] = {
            "pitchCount": _pitching_source_status(value=state.get("pitch_count_in_game"), source=pitch_count_source, status="available"),
            "timesThroughOrder": _pitching_source_status(value=state.get("times_through_order"), source="pitching_replay_scorer", status="model"),
            "velocityWindow": _pitching_source_status(value=state.get("velo_mean_5"), source="statcast_tracking_window", status="model"),
            "spinWindow": _pitching_source_status(value=state.get("spin_mean_5"), source="statcast_tracking_window", status="model" if state.get("spin_mean_5") is not None else "unavailable"),
            "locationDispersion": _pitching_source_status(value=state.get("location_dispersion_10"), source="pitching_replay_model_from_tracking", status="model"),
            "zoneMissDistance": _pitching_source_status(value=state.get("zone_miss_distance_10"), source="pitching_replay_model_from_tracking", status="model"),
            "hardContact": _pitching_source_status(value=state.get("hard_contact_rate_15"), source="pitching_replay_model_from_batted_ball_proxy", status="model"),
            "whiff": _pitching_source_status(value=state.get("whiff_rate_15"), source="pitching_replay_model_from_pitch_outcomes", status="model" if state.get("whiff_rate_15") is not None else "unavailable"),
            "ballRate": _pitching_source_status(value=state.get("ball_rate_10"), source="pitching_replay_model_from_pitch_outcomes", status="model" if state.get("ball_rate_10") is not None else "unavailable"),
            "pitchMixDrift": _pitching_source_status(value=state.get("pitch_mix_drift_10"), source="pitching_replay_model", status="model" if state.get("pitch_mix_drift_10") is not None else "unavailable"),
            "degradation": _pitching_source_status(value=state.get("degradation_score"), source="pitching_replay_degradation_model", status="model"),
        }
        snapshot["starter_state"] = state
        entry["snapshot"] = snapshot
        entry_rows.append(entry)
    normalized["entries"] = entry_rows
    summary = dict(normalized.get("summary") or {})
    summary["sourceStatus"] = {
        "replay": _pitching_source_status(value=entry_rows, source="pitching_replay_artifact", status="available" if entry_rows else "unavailable"),
        "pitchFacts": _pitching_source_status(value=True if has_pitch_facts else None, source="statsapi_live_game_feed_pitch_facts", status="available" if has_pitch_facts else "unavailable"),
    }
    normalized["summary"] = summary
    return normalized


def _load_pitching_official_pitch_facts(game_id: str, *, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any] | None:
    league_cache = STATE.pitching_official_pitch_facts_cache.setdefault(league, {})
    cached = league_cache.get(str(game_id))
    if isinstance(cached, dict) and cached:
        return dict(cached)

    try:
        game_pk = int(str(game_id))
    except (TypeError, ValueError):
        return None

    try:
        from infra.modal.live_signal_scorer import parse_live_feed_pitches
    except Exception:
        return None

    try:
        feed = _fetch_json(f"{MLB_STATS_API}/api/v1.1/game/{game_pk}/feed/live")
        parsed_pitches = parse_live_feed_pitches(game_pk, feed, after_at_bat=-1, after_pitch_index=-1)
    except Exception:
        return None

    facts = build_pitch_fact_payload(game_pk, parsed_pitches)
    if not facts.get("facts"):
        return None
    league_cache[str(game_id)] = dict(facts)
    return dict(facts)


def _load_pitching_official_boxscore(game_id: str, *, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, dict[str, Any]]:
    league_cache = STATE.pitching_official_boxscore_cache.setdefault(league, {})
    cached = league_cache.get(str(game_id))
    if isinstance(cached, dict) and cached:
        return {str(pid): dict(row) for pid, row in cached.items() if isinstance(row, dict)}

    def _boxscore_int(value: Any) -> int | None:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except Exception:
            return None

    try:
        game_pk = int(str(game_id))
    except (TypeError, ValueError):
        return {}

    try:
        feed = _fetch_json(f"{MLB_STATS_API}/api/v1.1/game/{game_pk}/feed/live")
    except Exception:
        return {}

    result: dict[str, dict[str, Any]] = {}
    boxscore = (feed.get("liveData") or {}).get("boxscore") or {}
    game_teams = (feed.get("gameData") or {}).get("teams") or {}
    for side in ("home", "away"):
        team_data = (boxscore.get("teams") or {}).get(side, {})
        team_abbr = str((game_teams.get(side) or {}).get("abbreviation") or "?")
        pitcher_ids = team_data.get("pitchers") or []
        players = team_data.get("players") or {}
        for appearance_order, pid in enumerate(pitcher_ids):
            player = players.get(f"ID{pid}") or {}
            stats = ((player.get("stats") or {}).get("pitching") or {})
            if not stats:
                continue
            result[str(pid)] = {
                "name": str((player.get("person") or {}).get("fullName") or pid),
                "team": team_abbr,
                "ip": stats.get("inningsPitched"),
                "h": _boxscore_int(stats.get("hits")),
                "r": _boxscore_int(stats.get("runs")),
                "er": _boxscore_int(stats.get("earnedRuns")),
                "bb": _boxscore_int(stats.get("baseOnBalls")),
                "so": _boxscore_int(stats.get("strikeOuts")),
                "hr": _boxscore_int(stats.get("homeRuns")),
                "np": _boxscore_int(stats.get("numberOfPitches")),
                "appearance_order": appearance_order,
            }
    if result:
        league_cache[str(game_id)] = {str(pid): dict(row) for pid, row in result.items()}
    return result


def _load_pitching_official_game_score(game_id: str, *, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any]:
    league_cache = STATE.pitching_official_game_score_cache.setdefault(league, {})
    cached = league_cache.get(str(game_id))
    if isinstance(cached, dict) and cached:
        return dict(cached)

    def _score_int(value: Any) -> int | None:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except Exception:
            return None

    try:
        game_pk = int(str(game_id))
    except (TypeError, ValueError):
        return {}

    try:
        feed = _fetch_json(f"{MLB_STATS_API}/api/v1.1/game/{game_pk}/feed/live")
    except Exception:
        return {}

    linescore = (feed.get("liveData") or {}).get("linescore") or {}
    teams = (linescore.get("teams") or {})
    game_teams = (feed.get("gameData") or {}).get("teams") or {}
    result = {
        "home_score": _score_int((teams.get("home") or {}).get("runs")),
        "away_score": _score_int((teams.get("away") or {}).get("runs")),
        "home_hits": _score_int((teams.get("home") or {}).get("hits")),
        "away_hits": _score_int((teams.get("away") or {}).get("hits")),
        "home_errors": _score_int((teams.get("home") or {}).get("errors")),
        "away_errors": _score_int((teams.get("away") or {}).get("errors")),
        "home_team": str((game_teams.get("home") or {}).get("abbreviation") or ""),
        "away_team": str((game_teams.get("away") or {}).get("abbreviation") or ""),
        "innings": [
            {
                "num": _score_int(inning.get("num")),
                "home": _score_int(((inning.get("home") or {}).get("runs"))),
                "away": _score_int(((inning.get("away") or {}).get("runs"))),
            }
            for inning in (linescore.get("innings") or [])
            if isinstance(inning, dict)
        ],
    }
    if result.get("home_score") is not None and result.get("away_score") is not None:
        league_cache[str(game_id)] = dict(result)
    return result


def _load_pitching_game_meta(
    game_id: str,
    *,
    league: str = DEFAULT_PITCHING_LEAGUE,
) -> dict[str, Any]:
    meta = _live_signal_store_get(live_signal_game_store, game_id, {})
    if not isinstance(meta, dict):
        meta = {}

    needs_signal_backfill = not (
        isinstance(meta.get("pitcher_states"), dict)
        and meta.get("pitcher_states")
        and isinstance(meta.get("backfill_signals"), dict)
    )
    if needs_signal_backfill and game_id:
        try:
            from infra.modal.live_signal_app import _backfill_game_scorer

            _backfill_game_scorer(int(game_id))
            refreshed = _live_signal_store_get(live_signal_game_store, game_id, {})
            if isinstance(refreshed, dict) and refreshed:
                meta = refreshed
        except Exception as exc:
            print(
                f"[abs-modal] pitching game meta backfill failed "
                f"league={league} game_id={game_id} error={exc}"
            )

    needs_context = not (
        isinstance(meta.get("player_names"), dict)
        and meta.get("player_names")
    )
    if needs_context and game_id:
        try:
            context_by_game, context_summary = build_pitching_game_context(
                [game_id],
                timeout=STATSAPI_CONTEXT_TIMEOUT_SECONDS,
            )
            context = context_by_game.get(str(game_id))
            if isinstance(context, dict) and context:
                merged = dict(meta)
                for key in ("home_team", "away_team", "player_names", "active_rosters"):
                    value = context.get(key)
                    if value:
                        merged[key] = value
                meta = merged
            print(
                f"[abs-modal] pitching game context hydrated "
                f"league={league} game_id={game_id} context={dict(context_summary or {})}"
            )
        except Exception as exc:
            print(
                f"[abs-modal] pitching game context hydration failed "
                f"league={league} game_id={game_id} error={exc}"
            )

    needs_boxscore = not (
        isinstance(meta.get("official_pitching_boxscore"), dict)
        and meta.get("official_pitching_boxscore")
    )
    if needs_boxscore and game_id:
        try:
            official_boxscore = _load_pitching_official_boxscore(game_id, league=league)
            if official_boxscore:
                merged = dict(meta)
                merged["official_pitching_boxscore"] = official_boxscore
                meta = merged
        except Exception as exc:
            print(
                f"[abs-modal] pitching boxscore hydration failed "
                f"league={league} game_id={game_id} error={exc}"
            )

    return meta


def _hydrate_batter_names(payload: dict[str, Any], *, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any]:
    game = payload.get("game") if isinstance(payload.get("game"), dict) else {}
    game_id = str(game.get("game_id") or "").strip()
    if not game_id:
        return payload
    try:
        meta = _load_pitching_game_meta(game_id, league=league)
    except Exception as exc:
        print(f"[abs-modal] batter-name hydration meta load failed game_id={game_id} error={exc}")
        return payload
    player_names = meta.get("player_names") if isinstance(meta.get("player_names"), dict) else {}
    if not player_names:
        print(f"[abs-modal] batter-name hydration skipped (no player_names) game_id={game_id}")
        return payload
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return payload
    overrides = 0
    misses = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        snap = entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else None
        if snap is None:
            continue
        batter_id = str(snap.get("batter_id") or "").strip()
        if not batter_id:
            continue
        current = str(snap.get("batter_name") or "").strip()
        if current and current != batter_id and not current.isdigit():
            continue
        real_name = str(player_names.get(batter_id) or "").strip()
        if real_name and real_name != batter_id:
            snap["batter_name"] = real_name
            overrides += 1
        else:
            misses += 1
    print(f"[abs-modal] batter-name hydration done game_id={game_id} overrides={overrides} misses={misses} dict_size={len(player_names)}")
    return payload


def _augment_pitching_replay_payload(payload: dict[str, Any], *, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any]:
    normalized = _normalize_pitching_replay_payload(dict(payload))
    game = dict(normalized.get("game") or {})
    game_id = str(game.get("game_id") or "")
    if not game_id:
        return _augment_pitching_replay_source_status(normalized, has_pitch_facts=False)
    normalized = _hydrate_batter_names(normalized, league=league)
    pitch_facts = _load_pitching_official_pitch_facts(game_id, league=league)
    if not isinstance(pitch_facts, dict):
        return _augment_pitching_replay_source_status(normalized, has_pitch_facts=False)
    augmented = augment_replay_payload_with_pitch_facts(normalized, pitch_facts)
    return _augment_pitching_replay_source_status(augmented, has_pitch_facts=True)


def _augment_pitching_audit_payload(payload: dict[str, Any], *, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any]:
    game_ids: set[str] = set()

    def _collect(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                _collect(item)
            return
        if isinstance(value, dict):
            game_id = str(value.get("game_id") or "")
            pitch_id = str(value.get("pitch_id") or "")
            if game_id and pitch_id and isinstance(value.get("starter"), dict):
                game_ids.add(game_id)
            for child in value.values():
                _collect(child)

    _collect(payload)
    if not game_ids:
        return dict(payload)

    replay_payload_by_game: dict[str, dict[str, Any]] = {}
    pitch_facts_by_game: dict[str, dict[str, Any] | None] = {}
    for game_id in game_ids:
        replay = _get_pitching_replay(game_id, league=league)
        if isinstance(replay, dict):
            replay_payload_by_game[game_id] = replay
        pitch_facts_by_game[game_id] = _load_pitching_official_pitch_facts(game_id, league=league)

    return augment_audit_payload_with_pitch_facts(dict(payload), replay_payload_by_game, pitch_facts_by_game)


def _get_pitching_replay(game_id: str, *, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any] | None:
    _refresh_pitching_caches_if_stale(league=league)
    league_cache = STATE.pitching_replay_cache.setdefault(league, {})
    cached = league_cache.get(game_id)
    if isinstance(cached, dict) and cached:
        return _augment_pitching_replay_payload(dict(cached), league=league)
    try:
        payload = _pitching_store_get(_pitching_store_key("replay", game_id, league=league))
    except Exception:
        payload = None
    if isinstance(payload, dict):
        normalized = _normalize_pitching_replay_payload(dict(payload))
        league_cache[game_id] = dict(normalized)
        return _augment_pitching_replay_payload(normalized, league=league)
    return None


def _pitching_replay_share_public_payload(record: dict[str, Any]) -> dict[str, Any]:
    home_team = str(record.get("home_team") or "").strip().upper() or None
    away_team = str(record.get("away_team") or "").strip().upper() or None
    state = str(record.get("state") or "active").lower()
    if state == "active" and not is_pitching_replay_share_active(record):
        state = "expired"
    return {
        "grant_id": str(record.get("grant_id") or "").strip(),
        "game_id": str(record.get("game_id") or "").strip(),
        "team": str(record.get("team") or "").strip().upper(),
        "date": str(record.get("date") or "").strip() or None,
        "home_team": home_team,
        "away_team": away_team,
        "matchup": f"{away_team} @ {home_team}" if away_team and home_team else None,
        "recipient_hint": str(record.get("recipient_hint") or mask_email(record.get("recipient_email"))),
        "expires_at": str(record.get("expires_at") or "").strip() or None,
        "state": state,
        "access_url": build_pitching_replay_share_url(str(record.get("grant_id") or "").strip(), BRAIN_APP_BASE_URL),
    }


class NoOpSupabaseRepo:
    def log_recommendation(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        return

    def log_decision_telemetry(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        return

    def log_decision_telemetry_batch(self, payloads: list[dict[str, Any]]) -> None:  # noqa: ARG002
        return

    def upsert_presets(self, presets: list[dict[str, Any]]) -> None:  # noqa: ARG002
        return

    def write_stress_test_run(self, row: dict[str, Any]) -> None:  # noqa: ARG002
        return

    def update_stress_test_run_summary(self, run_at: str, summary: dict[str, Any]) -> None:  # noqa: ARG002
        return

    def write_ingestion_run(self, row: dict[str, Any]) -> None:  # noqa: ARG002
        return

    def upsert_model_version(self, row: dict[str, Any]) -> None:  # noqa: ARG002
        return

    def update_model_version_metadata(self, version_id: str, metadata: dict[str, Any]) -> None:  # noqa: ARG002
        return

    def get_model_version(self, version_id: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def get_latest_stress_test_run(self) -> dict[str, Any] | None:
        return None

    def get_recent_stress_test_runs(self, limit: int = 5) -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    def get_latest_ingestion_run(self) -> dict[str, Any] | None:
        return None


def _build_repo(settings: Settings) -> SupabaseRepo | NoOpSupabaseRepo:
    if settings.disable_supabase:
        print("[abs-modal] Supabase disabled; using no-op repository")
        return NoOpSupabaseRepo()
    try:
        return SupabaseRepo(settings)
    except Exception as exc:  # pragma: no cover
        print(f"[abs-modal] Supabase unavailable ({exc}); using no-op repository")
        return NoOpSupabaseRepo()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_pitching_refresh_window(*, league: str = DEFAULT_PITCHING_LEAGUE) -> tuple[str | None, str | None]:
    normalized_league = _normalize_pitching_league(league)
    if normalized_league == TRIPLE_A_PITCHING_LEAGUE:
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        return today, today
    return None, None


def _pitching_refresh_source_label(*, league: str) -> str:
    normalized_league = _normalize_pitching_league(league)
    if normalized_league == TRIPLE_A_PITCHING_LEAGUE:
        return "triple_a_feed_live"
    return "mlb_statcast"


def _refresh_pitching_artifacts(
    settings: Settings,
    *,
    requested_at: str | None = None,
    league: str = DEFAULT_PITCHING_LEAGUE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    league = _normalize_pitching_league(league)
    started_at = _utc_now_iso()
    running = _default_pitching_refresh_status()
    default_start_date, default_end_date = _default_pitching_refresh_window(league=league)
    resolved_start_date = str(start_date or default_start_date or "").strip() or None
    resolved_end_date = str(end_date or default_end_date or resolved_start_date or "").strip() or None
    running.update(
        {
            "status": "running",
            "active": True,
            "requested_at": requested_at or started_at,
            "started_at": started_at,
            "league": league,
            "start_date": resolved_start_date,
            "end_date": resolved_end_date,
        }
    )
    STATE.pitching_refresh_status[league] = running
    _persist_pitching_refresh_status(running, league=league)
    try:
        triple_a_game_context_by_id: dict[str, dict[str, Any]] | None = None
        triple_a_context_summary: dict[str, Any] | None = None
        prior_summary = _get_pitching_summary(league=league) or {}
        prior_games = _get_pitching_games(league=league)
        if league == TRIPLE_A_PITCHING_LEAGUE:
            if not resolved_start_date or not resolved_end_date:
                raise ValueError("Triple-A pitching refresh requires a start_date and end_date")
            export_result = export_triple_a_pitching_csv(
                start_date=resolved_start_date,
                end_date=resolved_end_date,
            )
            statcast_csv_path = export_result.csv_path
            active_rosters_csv_path = None
            bullpen_roles_csv_path = None
            print(
                "[abs-modal] pitching refresh source prepared "
                f"league={league} source=triple_a_feed_live "
                f"window={resolved_start_date}..{resolved_end_date} "
                f"games={len(export_result.game_ids)} rows={export_result.row_count} "
                f"csv_path={statcast_csv_path}"
            )
            triple_a_game_context_by_id, triple_a_context_summary = build_pitching_game_context(
                export_result.game_ids,
                timeout=STATSAPI_CONTEXT_TIMEOUT_SECONDS,
            )
            print(
                "[abs-modal] pitching refresh context prepared "
                f"league={league} source=triple_a_feed_live "
                f"context={dict(triple_a_context_summary or {})}"
            )
            if int(export_result.row_count or 0) <= 0:
                completed = _default_pitching_refresh_status()
                completed.update(
                    {
                        "status": "completed",
                        "active": False,
                        "requested_at": requested_at or started_at,
                        "started_at": started_at,
                        "completed_at": _utc_now_iso(),
                        "generated_at": prior_summary.get("generated_at"),
                        "snapshot_count": prior_summary.get("snapshot_count"),
                        "game_count": prior_summary.get("game_count"),
                        "league": league,
                        "start_date": resolved_start_date,
                        "end_date": resolved_end_date,
                        "requested_window_empty": True,
                        "artifacts_preserved": bool(prior_summary and prior_games),
                    }
                )
                if prior_summary and prior_games:
                    print(
                        "[abs-modal] pitching refresh preserved prior artifacts "
                        f"league={league} source=triple_a_feed_live "
                        f"window={resolved_start_date}..{resolved_end_date} "
                        f"prior_generated_at={prior_summary.get('generated_at')} "
                        f"prior_games={len(prior_games)}"
                    )
                else:
                    print(
                        "[abs-modal] pitching refresh completed with empty requested window "
                        f"league={league} source=triple_a_feed_live "
                        f"window={resolved_start_date}..{resolved_end_date}"
                    )
                STATE.pitching_refresh_status[league] = completed
                _persist_pitching_refresh_status(completed, league=league)
                return completed
        else:
            active_rosters_csv_path = settings.abs_pitching_active_rosters_path
            if not active_rosters_csv_path and settings.abs_pitching_active_rosters_uri:
                active_rosters_csv_path = "/root/project/data/production/pitching_active_rosters.csv"
                fetch_csv_to_path(
                    settings.abs_pitching_active_rosters_uri,
                    active_rosters_csv_path,
                    timeout_seconds=60.0,
                )
            bullpen_roles_csv_path = settings.abs_pitching_bullpen_roles_path
            if not bullpen_roles_csv_path and settings.abs_pitching_bullpen_roles_uri:
                bullpen_roles_csv_path = "/root/project/data/production/pitching_bullpen_roles.csv"
                fetch_csv_to_path(
                    settings.abs_pitching_bullpen_roles_uri,
                    bullpen_roles_csv_path,
                    timeout_seconds=60.0,
                )
            statcast_csv_path = settings.abs_pitching_change_source_path
            print(
                "[abs-modal] pitching refresh source selected "
                f"league={league} source=mlb_statcast "
                f"window={resolved_start_date or 'default'}..{resolved_end_date or resolved_start_date or 'default'} "
                f"path={statcast_csv_path}"
            )
            if statcast_csv_path.startswith("http://") or statcast_csv_path.startswith("https://"):
                local_statcast_path = "/tmp/pitching_statcast_source.csv"
                print(
                    "[abs-modal] downloading pitching source "
                    f"league={league} source=mlb_statcast uri={statcast_csv_path}"
                )
                fetch_csv_to_path(statcast_csv_path, local_statcast_path, timeout_seconds=600.0)
                statcast_csv_path = local_statcast_path
            try:
                enriched_statcast_path = "/tmp/pitching_statcast_source_recent_schedule_enriched.csv"
                game_types = [part.strip() for part in settings.abs_mlb_game_types.split(",") if part.strip()] or ["R"]
                enrich_result = enrich_statcast_csv_with_recent_schedule_games(
                    input_csv_path=statcast_csv_path,
                    output_csv_path=enriched_statcast_path,
                    sport_id=settings.abs_mlb_sport_id,
                    game_types=game_types,
                    lookback_days=2,
                    timeout_seconds=20.0,
                    max_workers=6,
                )
                if int(enrich_result.get("fetched_game_count") or 0) > 0:
                    print(f"[abs-modal] pitching source enriched with recent schedule games: {enrich_result}")
                    statcast_csv_path = enriched_statcast_path
                elif enrich_result.get("failed_game_count"):
                    print(f"[abs-modal] pitching source recent schedule enrichment had misses: {enrich_result}")
            except Exception as enrich_exc:
                print(f"[abs-modal] pitching source recent schedule enrichment failed (non-fatal): {enrich_exc}")
        artifacts = build_pitching_change_artifacts(
            statcast_csv_path=statcast_csv_path,
            active_rosters_csv_path=active_rosters_csv_path,
            bullpen_roles_csv_path=bullpen_roles_csv_path,
            min_pitch_count=settings.abs_pitching_min_pitch_count,
            game_context_by_id_override=triple_a_game_context_by_id if league == TRIPLE_A_PITCHING_LEAGUE else None,
            discover_context_paths=league != TRIPLE_A_PITCHING_LEAGUE,
        )
        artifacts_summary = dict(artifacts.get("summary") or {})
        artifacts_summary["league"] = league
        if league == TRIPLE_A_PITCHING_LEAGUE:
            artifacts_summary["refresh_window"] = {
                "start_date": resolved_start_date,
                "end_date": resolved_end_date,
            }
            artifacts_summary["source_export"] = export_result.to_dict()
            artifacts_summary["statsapi_context"] = dict(triple_a_context_summary or {})
        artifacts["summary"] = artifacts_summary
        _set_pitching_artifacts(artifacts, league=league)
        completed = _default_pitching_refresh_status()
        completed.update(
            {
                "status": "completed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "generated_at": (artifacts.get("summary") or {}).get("generated_at"),
                "snapshot_count": (artifacts.get("summary") or {}).get("snapshot_count"),
                "game_count": (artifacts.get("summary") or {}).get("game_count"),
                "league": league,
                "start_date": resolved_start_date,
                "end_date": resolved_end_date,
                "requested_window_empty": False,
                "artifacts_preserved": False,
            }
        )
        STATE.pitching_refresh_status[league] = completed
        _persist_pitching_refresh_status(completed, league=league)
        return completed
    except Exception as exc:
        failed = _default_pitching_refresh_status()
        failed.update(
            {
                "status": "failed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "last_error": str(exc),
                "league": league,
                "start_date": resolved_start_date,
                "end_date": resolved_end_date,
            }
        )
        STATE.pitching_refresh_status[league] = failed
        _persist_pitching_refresh_status(failed, league=league)
        raise


def _calibration_default_start_date(season: int) -> str:
    if int(season) == 2026:
        return "2026-03-25"
    return f"{int(season)}-03-01"


def _default_pitching_calibration_end_date(*, season: int) -> str:
    sync_status = _load_data_sync_status()
    sync_date = str(sync_status.get("last_sync_date") or "").strip()
    if sync_date.startswith(str(int(season))):
        return sync_date
    summary = _get_pitching_summary(league=DEFAULT_PITCHING_LEAGUE) or {}
    max_game_date = str(summary.get("max_game_date") or "").strip()
    if max_game_date.startswith(str(int(season))):
        return max_game_date
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _validate_iso_date(value: str, *, label: str) -> str:
    token = str(value or "").strip()
    try:
        date.fromisoformat(token)
    except Exception as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD, got {value!r}") from exc
    return token


def _date_in_range(value: str, *, start_date: str, end_date: str) -> bool:
    token = str(value or "").strip()[:10]
    if not token:
        return False
    try:
        current = date.fromisoformat(token)
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except Exception:
        return False
    return start <= current <= end


def _statcast_row_game_date(row: dict[str, Any]) -> str:
    return str(row.get("game_date") or row.get("officialDate") or "").strip()[:10]


def _statcast_row_game_type(row: dict[str, Any]) -> str:
    return str(row.get("game_type") or row.get("gameType") or row.get("gameTypeCode") or "").strip().upper()


def _filter_statcast_csv_for_pitching_calibration(
    *,
    input_csv_path: str,
    output_csv_path: str,
    start_date: str,
    end_date: str,
    game_type: str = "R",
) -> dict[str, Any]:
    source = Path(input_csv_path)
    if not source.exists():
        raise FileNotFoundError(f"Calibration source CSV not found: {input_csv_path}")
    destination = Path(output_csv_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wanted_game_type = str(game_type or "").strip().upper()
    rows_read = 0
    rows_written = 0
    games: set[str] = set()
    dates: list[str] = []
    game_type_column_present = False
    with source.open("r", encoding="utf-8", newline="") as src, destination.open("w", encoding="utf-8", newline="") as dst:
        reader = csv.DictReader(src)
        fieldnames = list(reader.fieldnames or [])
        if not fieldnames:
            raise ValueError(f"Calibration source CSV has no header: {input_csv_path}")
        game_type_column_present = any(name in fieldnames for name in ("game_type", "gameType", "gameTypeCode"))
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            rows_read += 1
            game_date = _statcast_row_game_date(row)
            if not _date_in_range(game_date, start_date=start_date, end_date=end_date):
                continue
            if wanted_game_type and game_type_column_present:
                row_game_type = _statcast_row_game_type(row)
                if row_game_type and row_game_type != wanted_game_type:
                    continue
            writer.writerow(row)
            rows_written += 1
            dates.append(game_date)
            game_id = str(row.get("game_pk") or row.get("game_id") or "").strip()
            if game_id:
                games.add(game_id)
    return {
        "input_csv_path": input_csv_path,
        "output_csv_path": output_csv_path,
        "start_date": start_date,
        "end_date": end_date,
        "game_type": wanted_game_type or None,
        "game_type_column_present": game_type_column_present,
        "source_row_count": rows_read,
        "filtered_row_count": rows_written,
        "game_count": len(games),
        "min_game_date": min(dates) if dates else None,
        "max_game_date": max(dates) if dates else None,
    }


def _fetch_large_csv_to_path(
    source_uri: str,
    destination_path: str,
    *,
    timeout_seconds: float = 900.0,
    attempts: int = 4,
) -> None:
    import time as _time

    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        tmp_path = destination.with_suffix(f"{destination.suffix}.part{attempt}")
        try:
            req = UrlRequest(
                source_uri,
                method="GET",
                headers={
                    "User-Agent": "the-brain-pitching-calibration/1.0",
                    "Accept": "text/csv,*/*;q=0.8",
                },
            )
            with urlopen(req, timeout=timeout_seconds) as response, tmp_path.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 1024 * 8)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(tmp_path, destination)
            return
        except (IncompleteRead, TimeoutError, OSError, HTTPError, URLError) as exc:
            last_error = exc
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            if attempt >= attempts:
                break
            _time.sleep(min(30.0, 2.0 * attempt))
    raise RuntimeError(f"Failed to download calibration source after {attempts} attempts: {last_error}")


def _resolve_calibration_source_csv(settings: Settings) -> tuple[str, str]:
    statcast_source = settings.abs_pitching_change_source_path
    if not statcast_source:
        raise ValueError("ABS_PITCHING_CHANGE_SOURCE_PATH or ABS_RAW_STATCAST_URI is required")
    if statcast_source.startswith("http://") or statcast_source.startswith("https://"):
        local_path = "/tmp/pitching_calibration_statcast_source.csv"
        print(f"[abs-modal] pitching calibration downloading source uri={statcast_source}")
        _fetch_large_csv_to_path(statcast_source, local_path, timeout_seconds=900.0)
        return local_path, statcast_source
    return statcast_source, statcast_source


def _resolve_calibration_context_csvs(settings: Settings) -> tuple[str | None, str | None]:
    active_rosters_csv_path = settings.abs_pitching_active_rosters_path
    if not active_rosters_csv_path and settings.abs_pitching_active_rosters_uri:
        active_rosters_csv_path = "/tmp/pitching_calibration_active_rosters.csv"
        fetch_csv_to_path(settings.abs_pitching_active_rosters_uri, active_rosters_csv_path, timeout_seconds=60.0)
    bullpen_roles_csv_path = settings.abs_pitching_bullpen_roles_path
    if not bullpen_roles_csv_path and settings.abs_pitching_bullpen_roles_uri:
        bullpen_roles_csv_path = "/tmp/pitching_calibration_bullpen_roles.csv"
        fetch_csv_to_path(settings.abs_pitching_bullpen_roles_uri, bullpen_roles_csv_path, timeout_seconds=60.0)
    return active_rosters_csv_path, bullpen_roles_csv_path


def _supabase_public_object_target(settings: Settings, filename: str) -> str | None:
    source_url = str(settings.abs_raw_statcast_uri or "").strip()
    marker = "/storage/v1/object/public/"
    if not source_url or marker not in urlparse(source_url).path:
        return None
    base = source_url.rsplit("/", 1)[0]
    return f"{base}/pitching_calibration/{filename}"


def _upload_bytes_to_supabase_storage(
    settings: Settings,
    payload: bytes,
    target_public_url: str,
    *,
    content_type: str,
) -> None:
    if not settings.supabase_service_role_key:
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY is required for calibration artifact upload")
    parsed = urlparse(target_public_url)
    marker = "/storage/v1/object/public/"
    if marker not in parsed.path:
        raise ValueError(f"Not a Supabase public object URL: {target_public_url}")
    suffix = parsed.path.split(marker, 1)[1]
    bucket, _, object_path = suffix.partition("/")
    if not bucket or not object_path:
        raise ValueError(f"Could not parse bucket/object path from: {target_public_url}")
    upload_url = f"{parsed.scheme}://{parsed.netloc}/storage/v1/object/{bucket}/{object_path}"
    req = UrlRequest(
        upload_url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "apikey": settings.supabase_service_role_key,
            "x-upsert": "true",
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
        },
    )
    with urlopen(req, timeout=180) as response:
        if response.status not in {200, 201}:
            raise RuntimeError(f"Supabase calibration upload failed with status {response.status}")


def _write_calibration_rows_csv(rows: list[dict[str, Any]], output_path: str) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        destination.write_text("", encoding="utf-8")
        return
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _run_pitching_calibration(
    settings: Settings,
    *,
    requested_at: str | None = None,
    season: int = 2026,
    start_date: str | None = None,
    end_date: str | None = None,
    game_type: str = "R",
    min_pitch_count: int | None = None,
    upload_outputs: bool = True,
) -> dict[str, Any]:
    started_at = _utc_now_iso()
    resolved_season = int(season)
    resolved_start_date = _validate_iso_date(start_date or _calibration_default_start_date(resolved_season), label="start_date")
    resolved_end_date = _validate_iso_date(end_date or _default_pitching_calibration_end_date(season=resolved_season), label="end_date")
    resolved_game_type = str(game_type or "R").strip().upper() or "R"
    resolved_min_pitch_count = int(min_pitch_count or settings.abs_pitching_min_pitch_count)
    running = _default_pitching_calibration_status()
    running.update(
        {
            "status": "running",
            "active": True,
            "requested_at": requested_at or started_at,
            "started_at": started_at,
            "season": resolved_season,
            "start_date": resolved_start_date,
            "end_date": resolved_end_date,
            "game_type": resolved_game_type,
            "min_pitch_count": resolved_min_pitch_count,
        }
    )
    _persist_pitching_calibration_status(running, season=resolved_season)
    try:
        source_csv_path, source_label = _resolve_calibration_source_csv(settings)
        filtered_csv_path = f"/tmp/pitching_calibration_{resolved_season}_{resolved_start_date}_{resolved_end_date}.csv"
        filter_summary = _filter_statcast_csv_for_pitching_calibration(
            input_csv_path=source_csv_path,
            output_csv_path=filtered_csv_path,
            start_date=resolved_start_date,
            end_date=resolved_end_date,
            game_type=resolved_game_type,
        )
        if int(filter_summary.get("filtered_row_count") or 0) <= 0:
            raise ValueError(
                "Calibration source produced zero rows after filtering "
                f"{resolved_start_date}..{resolved_end_date} game_type={resolved_game_type}"
            )
        active_rosters_csv_path, bullpen_roles_csv_path = _resolve_calibration_context_csvs(settings)
        thresholds = PitchingDecisionThresholds()
        snapshots = build_pitching_decision_snapshots(
            filtered_csv_path,
            active_rosters_csv_path=active_rosters_csv_path,
            bullpen_roles_csv_path=bullpen_roles_csv_path,
            min_pitch_count=resolved_min_pitch_count,
        )
        calibration_report = build_pitching_score_calibration_report(snapshots, thresholds=thresholds)
        evaluation = evaluate_pitching_change_replay(snapshots, thresholds=thresholds).to_dict()
        generated_at = _utc_now_iso()
        safe_start = resolved_start_date.replace("-", "")
        safe_end = resolved_end_date.replace("-", "")
        prefix = f"pitching_calibration_{resolved_season}_{safe_start}_{safe_end}"
        rows = list(calibration_report.get("rows") or [])
        csv_path = f"/tmp/{prefix}_score_calibration.csv"
        summary_path = f"/tmp/{prefix}_score_calibration_summary.json"
        _write_calibration_rows_csv(rows, csv_path)
        summary_payload = {
            "generated_at": generated_at,
            "season": resolved_season,
            "start_date": resolved_start_date,
            "end_date": resolved_end_date,
            "game_type": resolved_game_type,
            "min_pitch_count": resolved_min_pitch_count,
            "source": {
                "configured_source": source_label,
                "local_source_csv": source_csv_path,
                "filtered_csv": filtered_csv_path,
                "filter": filter_summary,
                "active_rosters_csv": active_rosters_csv_path,
                "bullpen_roles_csv": bullpen_roles_csv_path,
            },
            "snapshot_count": len(snapshots),
            "calibration_row_count": len(rows),
            "evaluation": evaluation,
            "calibration": {
                key: value
                for key, value in calibration_report.items()
                if key != "rows"
            },
        }
        Path(summary_path).write_text(json.dumps(summary_payload, indent=2, sort_keys=True), encoding="utf-8")
        artifact_urls: dict[str, str] = {}
        upload_status = "skipped"
        if upload_outputs:
            csv_url = _supabase_public_object_target(settings, f"{prefix}_score_calibration.csv")
            summary_url = _supabase_public_object_target(settings, f"{prefix}_score_calibration_summary.json")
            if csv_url and summary_url:
                _upload_bytes_to_supabase_storage(
                    settings,
                    Path(csv_path).read_bytes(),
                    csv_url,
                    content_type="text/csv",
                )
                _upload_bytes_to_supabase_storage(
                    settings,
                    Path(summary_path).read_bytes(),
                    summary_url,
                    content_type="application/json",
                )
                artifact_urls = {
                    "score_calibration_csv": csv_url,
                    "score_calibration_summary_json": summary_url,
                }
                upload_status = "uploaded"
            else:
                upload_status = "skipped_no_supabase_public_source"
        summary_payload["artifacts"] = {
            "local_score_calibration_csv": csv_path,
            "local_score_calibration_summary_json": summary_path,
            "urls": artifact_urls,
            "upload_status": upload_status,
        }
        _pitching_store_put(_pitching_calibration_latest_key(season=resolved_season), summary_payload)
        completed = _default_pitching_calibration_status()
        completed.update(
            {
                "status": "completed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "generated_at": generated_at,
                "season": resolved_season,
                "start_date": resolved_start_date,
                "end_date": resolved_end_date,
                "game_type": resolved_game_type,
                "min_pitch_count": resolved_min_pitch_count,
                "source_row_count": filter_summary.get("source_row_count"),
                "filtered_row_count": filter_summary.get("filtered_row_count"),
                "game_count": filter_summary.get("game_count"),
                "snapshot_count": len(snapshots),
                "calibration_row_count": len(rows),
                "artifact_urls": artifact_urls,
                "upload_status": upload_status,
                "last_error": None,
            }
        )
        _persist_pitching_calibration_status(completed, season=resolved_season)
        return completed
    except Exception as exc:
        failed = _default_pitching_calibration_status()
        failed.update(
            {
                "status": "failed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "season": resolved_season,
                "start_date": resolved_start_date,
                "end_date": resolved_end_date,
                "game_type": resolved_game_type,
                "min_pitch_count": resolved_min_pitch_count,
                "last_error": str(exc),
            }
        )
        _persist_pitching_calibration_status(failed, season=resolved_season)
        raise


def _build_pitching_calibration_response(snapshot: dict[str, Any], *, season: int) -> dict[str, Any]:
    latest = _pitching_store_get(_pitching_calibration_latest_key(season=season))
    latest_summary = dict(latest or {}) if isinstance(latest, dict) else {}
    status = str(snapshot.get("status") or "idle")
    return {
        "status": "accepted" if status == "running" else status,
        "pitching_calibration_last_status": status,
        "requested_at": snapshot.get("requested_at"),
        "started_at": snapshot.get("started_at"),
        "completed_at": snapshot.get("completed_at"),
        "generated_at": latest_summary.get("generated_at") or snapshot.get("generated_at"),
        "season": int(season),
        "start_date": snapshot.get("start_date") or latest_summary.get("start_date"),
        "end_date": snapshot.get("end_date") or latest_summary.get("end_date"),
        "game_type": snapshot.get("game_type") or latest_summary.get("game_type"),
        "source_row_count": snapshot.get("source_row_count"),
        "filtered_row_count": snapshot.get("filtered_row_count"),
        "game_count": snapshot.get("game_count"),
        "snapshot_count": snapshot.get("snapshot_count") or latest_summary.get("snapshot_count"),
        "calibration_row_count": snapshot.get("calibration_row_count") or latest_summary.get("calibration_row_count"),
        "artifact_urls": snapshot.get("artifact_urls") or ((latest_summary.get("artifacts") or {}).get("urls") if isinstance(latest_summary.get("artifacts"), dict) else {}),
        "upload_status": snapshot.get("upload_status") or ((latest_summary.get("artifacts") or {}).get("upload_status") if isinstance(latest_summary.get("artifacts"), dict) else None),
        "last_error": snapshot.get("last_error"),
    }


def _start_background_pitching_calibration(
    *,
    season: int,
    start_date: str | None = None,
    end_date: str | None = None,
    game_type: str = "R",
    min_pitch_count: int | None = None,
    upload_outputs: bool = True,
) -> dict[str, Any]:
    existing = _load_pitching_calibration_status(season=season)
    if existing.get("active"):
        return existing
    requested_at = _utc_now_iso()
    running = _default_pitching_calibration_status()
    running.update(
        {
            "status": "running",
            "active": True,
            "requested_at": requested_at,
            "season": int(season),
            "start_date": start_date or _calibration_default_start_date(int(season)),
            "end_date": end_date or _default_pitching_calibration_end_date(season=int(season)),
            "game_type": str(game_type or "R").strip().upper() or "R",
            "min_pitch_count": min_pitch_count,
        }
    )
    _persist_pitching_calibration_status(running, season=season)
    try:
        job = pitching_calibration_job.spawn(
            requested_at=requested_at,
            season=int(season),
            start_date=start_date,
            end_date=end_date,
            game_type=game_type,
            min_pitch_count=min_pitch_count,
            upload_outputs=upload_outputs,
        )
        running["function_call_id"] = getattr(job, "object_id", None)
        _persist_pitching_calibration_status(running, season=season)
        return running
    except Exception as exc:
        failed = _default_pitching_calibration_status()
        failed.update(
            {
                "status": "failed",
                "active": False,
                "requested_at": requested_at,
                "completed_at": _utc_now_iso(),
                "season": int(season),
                "start_date": start_date,
                "end_date": end_date,
                "game_type": str(game_type or "R").strip().upper() or "R",
                "min_pitch_count": min_pitch_count,
                "last_error": str(exc),
            }
        )
        _persist_pitching_calibration_status(failed, season=season)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _default_preventable_training_start_date(season: int) -> str:
    previous = int(season) - 1
    if previous == 2025:
        return "2025-03-18"
    return f"{previous}-03-01"


def _default_preventable_training_end_date(season: int) -> str:
    return f"{int(season) - 1}-11-30"


def _default_preventable_holdout_start_date(season: int) -> str:
    return _calibration_default_start_date(int(season))


def _run_pitching_preventable_runs_model(
    settings: Settings,
    *,
    requested_at: str | None = None,
    season: int = 2026,
    training_start_date: str | None = None,
    training_end_date: str | None = None,
    holdout_start_date: str | None = None,
    holdout_end_date: str | None = None,
    game_type: str = "R",
    min_pitch_count: int | None = None,
    upload_outputs: bool = True,
) -> dict[str, Any]:
    started_at = _utc_now_iso()
    resolved_season = int(season)
    resolved_training_start = _validate_iso_date(
        training_start_date or _default_preventable_training_start_date(resolved_season),
        label="training_start_date",
    )
    resolved_training_end = _validate_iso_date(
        training_end_date or _default_preventable_training_end_date(resolved_season),
        label="training_end_date",
    )
    resolved_holdout_start = _validate_iso_date(
        holdout_start_date or _default_preventable_holdout_start_date(resolved_season),
        label="holdout_start_date",
    )
    resolved_holdout_end = _validate_iso_date(
        holdout_end_date or _default_pitching_calibration_end_date(season=resolved_season),
        label="holdout_end_date",
    )
    resolved_game_type = str(game_type or "R").strip().upper() or "R"
    resolved_min_pitch_count = int(min_pitch_count or settings.abs_pitching_min_pitch_count)
    running = _default_pitching_preventable_model_status()
    running.update(
        {
            "status": "running",
            "active": True,
            "requested_at": requested_at or started_at,
            "started_at": started_at,
            "season": resolved_season,
            "training_start_date": resolved_training_start,
            "training_end_date": resolved_training_end,
            "holdout_start_date": resolved_holdout_start,
            "holdout_end_date": resolved_holdout_end,
            "game_type": resolved_game_type,
            "min_pitch_count": resolved_min_pitch_count,
        }
    )
    _persist_pitching_preventable_model_status(running, season=resolved_season)
    try:
        source_csv_path, source_label = _resolve_calibration_source_csv(settings)
        training_csv_path = (
            f"/tmp/pitching_preventable_training_{resolved_season}_{resolved_training_start}_{resolved_training_end}.csv"
        )
        holdout_csv_path = (
            f"/tmp/pitching_preventable_holdout_{resolved_season}_{resolved_holdout_start}_{resolved_holdout_end}.csv"
        )
        training_filter = _filter_statcast_csv_for_pitching_calibration(
            input_csv_path=source_csv_path,
            output_csv_path=training_csv_path,
            start_date=resolved_training_start,
            end_date=resolved_training_end,
            game_type=resolved_game_type,
        )
        holdout_filter = _filter_statcast_csv_for_pitching_calibration(
            input_csv_path=source_csv_path,
            output_csv_path=holdout_csv_path,
            start_date=resolved_holdout_start,
            end_date=resolved_holdout_end,
            game_type=resolved_game_type,
        )
        if int(training_filter.get("filtered_row_count") or 0) <= 0:
            raise ValueError(
                "Preventable-runs training source produced zero rows after filtering "
                f"{resolved_training_start}..{resolved_training_end} game_type={resolved_game_type}"
            )
        if int(holdout_filter.get("filtered_row_count") or 0) <= 0:
            raise ValueError(
                "Preventable-runs holdout source produced zero rows after filtering "
                f"{resolved_holdout_start}..{resolved_holdout_end} game_type={resolved_game_type}"
            )

        active_rosters_csv_path, bullpen_roles_csv_path = _resolve_calibration_context_csvs(settings)
        thresholds = PitchingDecisionThresholds()
        training_snapshots = build_pitching_decision_snapshots(
            training_csv_path,
            active_rosters_csv_path=active_rosters_csv_path,
            bullpen_roles_csv_path=bullpen_roles_csv_path,
            min_pitch_count=resolved_min_pitch_count,
        )
        holdout_snapshots = build_pitching_decision_snapshots(
            holdout_csv_path,
            active_rosters_csv_path=active_rosters_csv_path,
            bullpen_roles_csv_path=bullpen_roles_csv_path,
            min_pitch_count=resolved_min_pitch_count,
        )
        training_report = build_pitching_score_calibration_report(training_snapshots, thresholds=thresholds)
        holdout_report = build_pitching_score_calibration_report(holdout_snapshots, thresholds=thresholds)
        training_rows = list(training_report.get("rows") or [])
        holdout_rows = list(holdout_report.get("rows") or [])
        training_formal_validation = (
            (training_report.get("componentRegressionBacktest") or {}).get("formalValidation") or {}
        )
        train_holdout_validation = build_degradation_train_holdout_validation(
            training_rows,
            holdout_rows,
            training_formal_validation=training_formal_validation,
        )
        model = build_pitching_preventable_runs_calibration_model(
            training_rows,
            holdout_rows=holdout_rows,
        )
        holdout_scored_rows = score_pitching_preventable_runs_rows(holdout_rows, model)
        opportunity_payload = _build_preventable_runs_opportunity_payload(holdout_scored_rows)
        generated_at = _utc_now_iso()
        safe_train_start = resolved_training_start.replace("-", "")
        safe_train_end = resolved_training_end.replace("-", "")
        safe_holdout_start = resolved_holdout_start.replace("-", "")
        safe_holdout_end = resolved_holdout_end.replace("-", "")
        prefix = (
            f"pitching_preventable_runs_model_{resolved_season}_"
            f"train{safe_train_start}_{safe_train_end}_holdout{safe_holdout_start}_{safe_holdout_end}"
        )
        model_path = f"/tmp/{prefix}.json"
        holdout_csv_scored_path = f"/tmp/{prefix}_holdout_scored.csv"
        summary_payload = {
            "generated_at": generated_at,
            "season": resolved_season,
            "training_start_date": resolved_training_start,
            "training_end_date": resolved_training_end,
            "holdout_start_date": resolved_holdout_start,
            "holdout_end_date": resolved_holdout_end,
            "game_type": resolved_game_type,
            "min_pitch_count": resolved_min_pitch_count,
            "source": {
                "configured_source": source_label,
                "local_source_csv": source_csv_path,
                "training_filtered_csv": training_csv_path,
                "holdout_filtered_csv": holdout_csv_path,
                "training_filter": training_filter,
                "holdout_filter": holdout_filter,
                "active_rosters_csv": active_rosters_csv_path,
                "bullpen_roles_csv": bullpen_roles_csv_path,
            },
            "training_snapshot_count": len(training_snapshots),
            "holdout_snapshot_count": len(holdout_snapshots),
            "training_calibration_row_count": len(training_rows),
            "holdout_calibration_row_count": len(holdout_rows),
            "trainingEvaluation": evaluate_pitching_change_replay(training_snapshots, thresholds=thresholds).to_dict(),
            "holdoutEvaluation": evaluate_pitching_change_replay(holdout_snapshots, thresholds=thresholds).to_dict(),
            "model": model,
            "opportunities": opportunity_payload,
            "modelInputs": {
                "trainingScoreSummaries": training_report.get("scoreSummaries"),
                "holdoutScoreSummaries": holdout_report.get("scoreSummaries"),
                "trainingComponentRegressionBacktest": training_report.get("componentRegressionBacktest"),
                "holdoutComponentRegressionBacktest": holdout_report.get("componentRegressionBacktest"),
                "trainHoldoutDegradationValidation": train_holdout_validation,
                "outcomeDefinitions": ((training_report.get("summary") or {}).get("outcomeDefinitions") or {}),
            },
        }
        Path(model_path).write_text(json.dumps(summary_payload, indent=2, sort_keys=True), encoding="utf-8")
        _write_calibration_rows_csv(holdout_scored_rows, holdout_csv_scored_path)
        artifact_urls: dict[str, str] = {}
        upload_status = "skipped"
        if upload_outputs:
            model_url = _supabase_public_object_target(settings, f"{prefix}.json")
            holdout_scored_url = _supabase_public_object_target(settings, f"{prefix}_holdout_scored.csv")
            if model_url and holdout_scored_url:
                _upload_bytes_to_supabase_storage(
                    settings,
                    Path(model_path).read_bytes(),
                    model_url,
                    content_type="application/json",
                )
                _upload_bytes_to_supabase_storage(
                    settings,
                    Path(holdout_csv_scored_path).read_bytes(),
                    holdout_scored_url,
                    content_type="text/csv",
                )
                artifact_urls = {
                    "preventable_runs_model_json": model_url,
                    "holdout_scored_csv": holdout_scored_url,
                }
                upload_status = "uploaded"
            else:
                upload_status = "skipped_no_supabase_public_source"
        summary_payload["artifacts"] = {
            "local_preventable_runs_model_json": model_path,
            "local_holdout_scored_csv": holdout_csv_scored_path,
            "urls": artifact_urls,
            "upload_status": upload_status,
        }
        _pitching_store_put(_pitching_preventable_model_latest_key(season=resolved_season), summary_payload)
        completed = _default_pitching_preventable_model_status()
        completed.update(
            {
                "status": "completed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "generated_at": generated_at,
                "season": resolved_season,
                "training_start_date": resolved_training_start,
                "training_end_date": resolved_training_end,
                "holdout_start_date": resolved_holdout_start,
                "holdout_end_date": resolved_holdout_end,
                "game_type": resolved_game_type,
                "min_pitch_count": resolved_min_pitch_count,
                "source_row_count": training_filter.get("source_row_count"),
                "training_filtered_row_count": training_filter.get("filtered_row_count"),
                "holdout_filtered_row_count": holdout_filter.get("filtered_row_count"),
                "training_game_count": training_filter.get("game_count"),
                "holdout_game_count": holdout_filter.get("game_count"),
                "training_snapshot_count": len(training_snapshots),
                "holdout_snapshot_count": len(holdout_snapshots),
                "training_calibration_row_count": len(training_rows),
                "holdout_calibration_row_count": len(holdout_rows),
                "artifact_urls": artifact_urls,
                "upload_status": upload_status,
                "last_error": None,
            }
        )
        _persist_pitching_preventable_model_status(completed, season=resolved_season)
        return completed
    except Exception as exc:
        failed = _default_pitching_preventable_model_status()
        failed.update(
            {
                "status": "failed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "season": resolved_season,
                "training_start_date": resolved_training_start,
                "training_end_date": resolved_training_end,
                "holdout_start_date": resolved_holdout_start,
                "holdout_end_date": resolved_holdout_end,
                "game_type": resolved_game_type,
                "min_pitch_count": resolved_min_pitch_count,
                "last_error": str(exc),
            }
        )
        _persist_pitching_preventable_model_status(failed, season=resolved_season)
        raise


def _preventable_runs_model_number(value: Any, *, digits: int = 6) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
    except Exception:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits)


def _preventable_runs_model_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def _preventable_runs_model_mean(values: Iterable[Any]) -> float | None:
    clean = [
        float(number)
        for value in values
        if (number := _preventable_runs_model_number(value)) is not None
    ]
    if not clean:
        return None
    return round(sum(clean) / float(len(clean)), 6)


def _preventable_runs_model_feature_contributions(row: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    raw = row.get("feature_contributions_json")
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    contributions = [item for item in parsed if isinstance(item, dict)]
    contributions.sort(key=lambda item: float(item.get("contribution") or 0.0), reverse=True)
    return contributions[:limit]


def _preventable_runs_peak_window_sort_key(row: dict[str, Any]) -> tuple[int, float, float, int]:
    status = str(row.get("recommendation_status") or row.get("recommendationStatus") or "").upper().replace(" ", "_")
    return (
        1 if status == "PULL_NOW" else 0,
        float(row.get("decision_delta") or row.get("decisionDelta") or 0.0),
        float(row.get("calibrated_preventable_signal") or row.get("calibratedPreventableSignal") or 0.0),
        int(row.get("pitch_count_in_game") or row.get("pitchCount") or 0),
    )


def _preventable_runs_game_bucket(row: dict[str, Any]) -> str:
    # Slide matrix axes:
    # - Starter late-inning stuff: normalized degradation below watch band is above average.
    # - Bullpen quality: best available reliever net option after usage cost.
    starter_degradation = _preventable_runs_model_number(
        (
            row.get("normalized_degradation")
            if row.get("normalized_degradation") is not None
            else row.get("normalizedDegradation")
        ),
        digits=6,
    )
    bullpen_value = _preventable_runs_model_number(
        (
            row.get("best_reliever_value_next_3_hitters")
            if row.get("best_reliever_value_next_3_hitters") is not None
            else row.get("bestRelieverValueNextWindow")
        ),
        digits=6,
    )
    if starter_degradation is None or bullpen_value is None:
        return "unclassified"
    starter_above_average = starter_degradation < 0.45
    bullpen_above_average = bullpen_value >= 0.65
    if starter_above_average and bullpen_above_average:
        return "standard"
    if not starter_above_average and bullpen_above_average:
        return "tandem"
    if starter_above_average and not bullpen_above_average:
        return "push"
    return "workload"


def _preventable_runs_model_opportunity_row(row: dict[str, Any]) -> dict[str, Any]:
    bucket = str(row.get("allocation_bucket") or row.get("allocationBucket") or "").strip().lower()
    return {
        "gameId": str(row.get("game_id") or ""),
        "gameDate": str(row.get("game_date") or ""),
        "fieldingTeam": str(row.get("fielding_team") or ""),
        "battingTeam": str(row.get("batting_team") or ""),
        "pitcherId": str(row.get("pitcher_id") or ""),
        "pitcherName": str(row.get("pitcher_name") or ""),
        "pitchId": str(row.get("pitch_id") or ""),
        "inning": _preventable_runs_model_int(row.get("inning")),
        "half": str(row.get("half") or ""),
        "outs": _preventable_runs_model_int(row.get("outs")),
        "baseState": str(row.get("base_state") or ""),
        "pitchCount": _preventable_runs_model_int(row.get("pitch_count_in_game")),
        "currentHomeScore": _preventable_runs_model_int(row.get("current_home_score") if row.get("current_home_score") is not None else row.get("currentHomeScore")),
        "currentAwayScore": _preventable_runs_model_int(row.get("current_away_score") if row.get("current_away_score") is not None else row.get("currentAwayScore")),
        "finalHomeScore": _preventable_runs_model_int(row.get("final_home_score") if row.get("final_home_score") is not None else row.get("finalHomeScore")),
        "finalAwayScore": _preventable_runs_model_int(row.get("final_away_score") if row.get("final_away_score") is not None else row.get("finalAwayScore")),
        "timesThroughOrder": _preventable_runs_model_int(row.get("times_through_order")),
        "leverageIndex": _preventable_runs_model_number(row.get("leverage_index"), digits=4),
        "recommendationStatus": str(row.get("recommendation_status") or ""),
        "productionDegradation": _preventable_runs_model_number(row.get("production_degradation"), digits=4),
        "normalizedDegradation": _preventable_runs_model_number(row.get("normalized_degradation"), digits=4),
        "recommendedRelieverId": str(row.get("recommended_reliever_id") or ""),
        "recommendedRelieverName": str(row.get("recommended_reliever_name") or ""),
        "starterValueNextWindow": _preventable_runs_model_number(row.get("starter_value_next_3_hitters"), digits=4),
        "bestRelieverValueNextWindow": _preventable_runs_model_number(row.get("best_reliever_value_next_3_hitters"), digits=4),
        "decisionDelta": _preventable_runs_model_number(row.get("decision_delta"), digits=4),
        "allocationBucket": bucket or _preventable_runs_game_bucket(row),
        "calibratedPreventableSignal": _preventable_runs_model_number(row.get("calibrated_preventable_signal"), digits=6),
        "projectedDamageProbability": _preventable_runs_model_number(row.get("projected_damage_probability"), digits=6),
        "projectedRunsThroughNextPocket": _preventable_runs_model_number(row.get("projected_runs_through_next_pocket"), digits=6),
        "projectedPreventableRuns": _preventable_runs_model_number(row.get("projected_preventable_runs"), digits=6),
        "calibrationBucket": _preventable_runs_model_int(row.get("calibration_bucket")),
        "calibrationSampleCount": _preventable_runs_model_int(row.get("calibration_sample_count")),
        "calibrationConfidence": _preventable_runs_model_number(row.get("calibration_confidence"), digits=6),
        "actualRunsThroughNextPocket": _preventable_runs_model_number(row.get("runs_through_next_pocket"), digits=6),
        "actualPreventableRunsProxy": _preventable_runs_model_number(row.get("preventable_runs_proxy"), digits=6),
        "damageFlag": _preventable_runs_model_int(row.get("damage_flag")),
        "missedHookDamageFlag": _preventable_runs_model_int(row.get("missed_hook_damage_flag")),
        "actualChangeWithinNextPocket": bool(_preventable_runs_model_int(row.get("actual_change_within_next_pocket"))),
        "actualReplacementPitcherId": str(row.get("actual_replacement_pitcher_id") or row.get("actualReplacementPitcherId") or ""),
        "actualChangePitchId": str(row.get("actual_change_pitch_id") or row.get("actualChangePitchId") or ""),
        "actualChangeAfterPitches": _preventable_runs_model_int(row.get("actual_change_after_pitches") if row.get("actual_change_after_pitches") is not None else row.get("actualChangeAfterPitches")),
        "actualChangeAfterBatters": _preventable_runs_model_int(row.get("actual_change_after_batters") if row.get("actual_change_after_batters") is not None else row.get("actualChangeAfterBatters")),
        "topFeatureContributions": _preventable_runs_model_feature_contributions(row),
    }


def _build_preventable_runs_team_game_matrix(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        team = str(row.get("fielding_team") or "").upper()
        game_id = str(row.get("game_id") or "")
        if team and game_id:
            grouped[(team, game_id)].append(row)

    by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (team, _game_id), game_rows in grouped.items():
        peak = max(game_rows, key=_preventable_runs_peak_window_sort_key)
        enriched = dict(peak)
        enriched["allocation_bucket"] = _preventable_runs_game_bucket(peak)
        payload = _preventable_runs_model_opportunity_row(enriched)
        payload["windowCount"] = len(game_rows)
        payload["peakWindow"] = True
        by_team[team].append(payload)

    for team_rows in by_team.values():
        team_rows.sort(
            key=lambda row: (
                float(row.get("decisionDelta") or 0.0),
                float(row.get("calibratedPreventableSignal") or 0.0),
                str(row.get("gameDate") or ""),
            ),
            reverse=True,
        )
    return dict(sorted(by_team.items()))


def _build_preventable_runs_opportunity_payload(
    scored_rows: list[dict[str, Any]],
    *,
    global_limit: int = 500,
    team_limit: int = 75,
    pitcher_limit: int = 500,
) -> dict[str, Any]:
    valid = [
        row
        for row in scored_rows
        if _preventable_runs_model_number(row.get("projected_preventable_runs")) is not None
        and _preventable_runs_model_number(row.get("calibrated_preventable_signal")) is not None
    ]
    valid.sort(
        key=lambda row: (
            float(row.get("projected_preventable_runs") or 0.0),
            float(row.get("calibrated_preventable_signal") or 0.0),
        ),
        reverse=True,
    )
    by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_pitcher: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in valid:
        team = str(row.get("fielding_team") or "").upper()
        pitcher_id = str(row.get("pitcher_id") or "")
        pitcher_name = str(row.get("pitcher_name") or "")
        if team:
            by_team[team].append(row)
        if team and pitcher_id:
            by_pitcher[(team, pitcher_id, pitcher_name)].append(row)

    def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "windowCount": len(rows),
            "totalProjectedPreventableRuns": round(
                sum(float(row.get("projected_preventable_runs") or 0.0) for row in rows),
                6,
            ),
            "avgProjectedPreventableRuns": _preventable_runs_model_mean(
                row.get("projected_preventable_runs") for row in rows
            ),
            "avgProjectedDamageProbability": _preventable_runs_model_mean(
                row.get("projected_damage_probability") for row in rows
            ),
            "actualPreventableRunsProxy": round(
                sum(float(row.get("preventable_runs_proxy") or 0.0) for row in rows),
                6,
            ),
            "damageRate": _preventable_runs_model_mean(row.get("damage_flag") for row in rows),
            "missedHookDamageCount": sum(int(row.get("missed_hook_damage_flag") or 0) for row in rows),
            "topOpportunity": _preventable_runs_model_opportunity_row(rows[0]) if rows else None,
        }

    team_summary = {
        team: {
            "team": team,
            **_group_summary(rows),
        }
        for team, rows in sorted(by_team.items())
    }
    pitcher_rows = []
    for (team, pitcher_id, pitcher_name), rows in by_pitcher.items():
        payload = {
            "team": team,
            "pitcherId": pitcher_id,
            "pitcherName": pitcher_name,
            **_group_summary(rows),
        }
        pitcher_rows.append(payload)
    pitcher_rows.sort(
        key=lambda item: (
            float(item.get("totalProjectedPreventableRuns") or 0.0),
            float((item.get("topOpportunity") or {}).get("projectedPreventableRuns") or 0.0),
        ),
        reverse=True,
    )
    team_top = {
        team: [_preventable_runs_model_opportunity_row(row) for row in rows[:team_limit]]
        for team, rows in sorted(by_team.items())
    }
    team_game_matrix = _build_preventable_runs_team_game_matrix(scored_rows)
    return {
        "status": "available" if valid else "unavailable_no_scored_rows",
        "scoredWindowCount": len(scored_rows),
        "validWindowCount": len(valid),
        "globalTop": [_preventable_runs_model_opportunity_row(row) for row in valid[:global_limit]],
        "teamSummary": team_summary,
        "teamTop": team_top,
        "teamGameMatrix": team_game_matrix,
        "pitcherSummaryTop": pitcher_rows[:pitcher_limit],
        "definitions": {
            "projectedPreventableRuns": "Calibrated historical opportunity proxy from comparable decision windows.",
            "actualPreventableRunsProxy": "Observed proxy on holdout windows, not a confirmed counterfactual.",
            "globalTop": "Highest projected preventable-run windows in the holdout set.",
            "teamGameMatrix": "One peak starter-decision window per team game, bucketed by starter late-inning stuff and bullpen quality.",
        },
    }


def _build_pitching_preventable_model_response(snapshot: dict[str, Any], *, season: int) -> dict[str, Any]:
    latest = _pitching_store_get(_pitching_preventable_model_latest_key(season=season))
    latest_summary = dict(latest or {}) if isinstance(latest, dict) else {}
    status = str(snapshot.get("status") or "idle")
    return {
        "status": "accepted" if status == "running" else status,
        "pitching_preventable_runs_model_last_status": status,
        "requested_at": snapshot.get("requested_at"),
        "started_at": snapshot.get("started_at"),
        "completed_at": snapshot.get("completed_at"),
        "generated_at": latest_summary.get("generated_at") or snapshot.get("generated_at"),
        "season": int(season),
        "training_start_date": snapshot.get("training_start_date") or latest_summary.get("training_start_date"),
        "training_end_date": snapshot.get("training_end_date") or latest_summary.get("training_end_date"),
        "holdout_start_date": snapshot.get("holdout_start_date") or latest_summary.get("holdout_start_date"),
        "holdout_end_date": snapshot.get("holdout_end_date") or latest_summary.get("holdout_end_date"),
        "game_type": snapshot.get("game_type") or latest_summary.get("game_type"),
        "source_row_count": snapshot.get("source_row_count"),
        "training_filtered_row_count": snapshot.get("training_filtered_row_count"),
        "holdout_filtered_row_count": snapshot.get("holdout_filtered_row_count"),
        "training_game_count": snapshot.get("training_game_count"),
        "holdout_game_count": snapshot.get("holdout_game_count"),
        "training_snapshot_count": snapshot.get("training_snapshot_count") or latest_summary.get("training_snapshot_count"),
        "holdout_snapshot_count": snapshot.get("holdout_snapshot_count") or latest_summary.get("holdout_snapshot_count"),
        "training_calibration_row_count": snapshot.get("training_calibration_row_count") or latest_summary.get("training_calibration_row_count"),
        "holdout_calibration_row_count": snapshot.get("holdout_calibration_row_count") or latest_summary.get("holdout_calibration_row_count"),
        "artifact_urls": snapshot.get("artifact_urls") or ((latest_summary.get("artifacts") or {}).get("urls") if isinstance(latest_summary.get("artifacts"), dict) else {}),
        "upload_status": snapshot.get("upload_status") or ((latest_summary.get("artifacts") or {}).get("upload_status") if isinstance(latest_summary.get("artifacts"), dict) else None),
        "model_status": ((latest_summary.get("model") or {}).get("status") if isinstance(latest_summary.get("model"), dict) else None),
        "last_error": snapshot.get("last_error"),
    }


def _start_background_pitching_preventable_runs_model(
    *,
    season: int,
    training_start_date: str | None = None,
    training_end_date: str | None = None,
    holdout_start_date: str | None = None,
    holdout_end_date: str | None = None,
    game_type: str = "R",
    min_pitch_count: int | None = None,
    upload_outputs: bool = True,
) -> dict[str, Any]:
    existing = _load_pitching_preventable_model_status(season=season)
    if existing.get("active"):
        stale = False
        started_at = existing.get("started_at") or existing.get("requested_at")
        if started_at:
            try:
                started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                age_minutes = (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds() / 60
                stale = age_minutes > 120
                if stale:
                    print(f"[abs-modal] preventable-runs model status stale ({age_minutes:.1f}m) — allowing re-trigger")
            except Exception:
                stale = True
        if not stale:
            return existing
    requested_at = _utc_now_iso()
    running = _default_pitching_preventable_model_status()
    running.update(
        {
            "status": "running",
            "active": True,
            "requested_at": requested_at,
            "season": int(season),
            "training_start_date": training_start_date or _default_preventable_training_start_date(int(season)),
            "training_end_date": training_end_date or _default_preventable_training_end_date(int(season)),
            "holdout_start_date": holdout_start_date or _default_preventable_holdout_start_date(int(season)),
            "holdout_end_date": holdout_end_date or _default_pitching_calibration_end_date(season=int(season)),
            "game_type": str(game_type or "R").strip().upper() or "R",
            "min_pitch_count": min_pitch_count,
        }
    )
    _persist_pitching_preventable_model_status(running, season=season)
    try:
        job = pitching_preventable_runs_model_job.spawn(
            requested_at=requested_at,
            season=int(season),
            training_start_date=training_start_date,
            training_end_date=training_end_date,
            holdout_start_date=holdout_start_date,
            holdout_end_date=holdout_end_date,
            game_type=game_type,
            min_pitch_count=min_pitch_count,
            upload_outputs=upload_outputs,
        )
        running["function_call_id"] = getattr(job, "object_id", None)
        _persist_pitching_preventable_model_status(running, season=season)
        return running
    except Exception as exc:
        failed = _default_pitching_preventable_model_status()
        failed.update(
            {
                "status": "failed",
                "active": False,
                "requested_at": requested_at,
                "completed_at": _utc_now_iso(),
                "season": int(season),
                "training_start_date": training_start_date,
                "training_end_date": training_end_date,
                "holdout_start_date": holdout_start_date,
                "holdout_end_date": holdout_end_date,
                "game_type": str(game_type or "R").strip().upper() or "R",
                "min_pitch_count": min_pitch_count,
                "last_error": str(exc),
            }
        )
        _persist_pitching_preventable_model_status(failed, season=season)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _fast_base_sims(settings: Settings) -> int:
    return max(1, min(settings.abs_intraday_sims, FAST_BASE_MAX_SIMS))


def _artifact_mode_label(artifact_mode: str) -> str:
    return artifact_mode if artifact_mode in {ARTIFACT_MODE_FAST_BASE, ARTIFACT_MODE_FULL_MATRIX} else ARTIFACT_MODE_FULL_MATRIX


def _default_recompute_status(artifact_mode: str) -> dict[str, Any]:
    return {
        "artifact_mode": _artifact_mode_label(artifact_mode),
        "status": "idle",
        "active": False,
        "requested_at": None,
        "started_at": None,
        "completed_at": None,
        "latest_generated_at": None,
        "last_error": None,
    }


def _stress_status_key(artifact_mode: str) -> str:
    return f"stress_recompute_status:{_artifact_mode_label(artifact_mode)}"


def _load_shared_recompute_status(artifact_mode: str) -> dict[str, Any] | None:
    try:
        payload = stress_status_store.get(_stress_status_key(artifact_mode))
    except Exception:
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _persist_shared_recompute_status(snapshot: dict[str, Any]) -> None:
    try:
        stress_status_store.put(_stress_status_key(str(snapshot.get("artifact_mode") or "")), snapshot)
    except Exception as exc:
        print(f"[abs-modal] failed to persist shared stress status: {exc}")


def _default_model_evaluation_status() -> dict[str, Any]:
    return {
        "status": "idle",
        "active": False,
        "requested_at": None,
        "started_at": None,
        "completed_at": None,
        "last_error": None,
    }


def _load_shared_model_evaluation_status() -> dict[str, Any] | None:
    try:
        payload = model_evaluation_status_store.get("model_evaluation_refresh_status")
    except Exception:
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _persist_shared_model_evaluation_status(snapshot: dict[str, Any]) -> None:
    try:
        model_evaluation_status_store.put("model_evaluation_refresh_status", snapshot)
    except Exception as exc:
        print(f"[abs-modal] failed to persist model-evaluation status: {exc}")


def _get_model_evaluation_status_snapshot() -> dict[str, Any]:
    snapshot = _default_model_evaluation_status()
    existing = STATE.model_evaluation_status
    if isinstance(existing, dict):
        snapshot.update(existing)
    shared = _load_shared_model_evaluation_status()
    if isinstance(shared, dict):
        snapshot.update(shared)
    return snapshot


def _set_model_evaluation_status(
    *,
    status: str,
    requested_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    last_error: str | None = None,
) -> dict[str, Any]:
    current = _get_model_evaluation_status_snapshot()
    current["status"] = status
    current["active"] = status == "running"
    if status == "running":
        current["completed_at"] = None
        if started_at is None and requested_at is not None:
            current["started_at"] = None
    if requested_at is not None:
        current["requested_at"] = requested_at
    if started_at is not None:
        current["started_at"] = started_at
    if completed_at is not None:
        current["completed_at"] = completed_at
    if last_error is not None or status == "failed":
        current["last_error"] = last_error
    elif status in {"completed", "running"}:
        current["last_error"] = None
    STATE.model_evaluation_status = current
    _persist_shared_model_evaluation_status(current)
    return dict(current)


def _get_recompute_status_snapshot(artifact_mode: str) -> dict[str, Any]:
    mode = _artifact_mode_label(artifact_mode)
    snapshot = _default_recompute_status(mode)
    existing = STATE.recompute_status.get(mode)
    if isinstance(existing, dict):
        snapshot.update(existing)
    shared = _load_shared_recompute_status(mode)
    if isinstance(shared, dict):
        snapshot.update(shared)
    future = STATE.recompute_futures.get(mode)
    if snapshot.get("status") == "running":
        snapshot["active"] = True
    if future is not None and not future.done():
        snapshot["active"] = True
        snapshot["status"] = "running"
    return snapshot


def _set_recompute_status(
    artifact_mode: str,
    *,
    status: str,
    requested_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    latest_generated_at: str | None = None,
    last_error: str | None = None,
) -> dict[str, Any]:
    mode = _artifact_mode_label(artifact_mode)
    current = _get_recompute_status_snapshot(mode)
    current["artifact_mode"] = mode
    current["status"] = status
    current["active"] = status == "running"
    if status == "running":
        current["completed_at"] = None
        if started_at is None and requested_at is not None:
            current["started_at"] = None
    if requested_at is not None:
        current["requested_at"] = requested_at
    if started_at is not None:
        current["started_at"] = started_at
    if completed_at is not None:
        current["completed_at"] = completed_at
    if latest_generated_at is not None:
        current["latest_generated_at"] = latest_generated_at
    if last_error is not None or status == "failed":
        current["last_error"] = last_error
    elif status in {"completed", "running"}:
        current["last_error"] = None
    STATE.recompute_status[mode] = current
    _persist_shared_recompute_status(current)
    return dict(current)


def _stress_row_artifact_mode(row: dict[str, Any]) -> str:
    summary = _coerce_dict(row.get("summary"))
    artifact_mode = str(summary.get("artifact_mode") or "").strip()
    if artifact_mode in {ARTIFACT_MODE_FAST_BASE, ARTIFACT_MODE_FULL_MATRIX}:
        return artifact_mode
    scenario_outcomes = summary.get("scenario_outcomes")
    if isinstance(scenario_outcomes, list) and len(scenario_outcomes) <= 1:
        return ARTIFACT_MODE_FAST_BASE
    return ARTIFACT_MODE_FULL_MATRIX


def _stress_row_valid(row: dict[str, Any]) -> bool:
    summary = _coerce_dict(row.get("summary"))
    scenario_outcomes = summary.get("scenario_outcomes")
    return isinstance(scenario_outcomes, list) and len(scenario_outcomes) > 0


def _stress_row_matches_artifact_mode(row: dict[str, Any], artifact_mode: str | None) -> bool:
    if artifact_mode is None:
        return True
    row_mode = _stress_row_artifact_mode(row)
    if artifact_mode == ARTIFACT_MODE_FULL_MATRIX:
        return row_mode == ARTIFACT_MODE_FULL_MATRIX
    return row_mode == artifact_mode


def _select_preferred_stress_row(
    rows: list[dict[str, Any]],
    artifact_mode: str | None = None,
) -> dict[str, Any] | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not _stress_row_valid(row):
            continue
        if not _stress_row_matches_artifact_mode(row, artifact_mode):
            continue
        return row
    return None


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if pct <= 0:
        return ordered[0]
    if pct >= 100:
        return ordered[-1]
    pos = (len(ordered) - 1) * (pct / 100.0)
    lower = int(pos)
    upper = min(len(ordered) - 1, lower + 1)
    if lower == upper:
        return ordered[lower]
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _ingest_freshness_seconds(last_ingest_at: str | None) -> int | None:
    if not last_ingest_at:
        return None
    try:
        ingest_dt = datetime.fromisoformat(last_ingest_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(timezone.utc) - ingest_dt).total_seconds()))


def _coerce_boolish(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    text = str(value).strip().lower()
    if text in {"", "0", "false", "no", "n", "null", "none"}:
        return False
    if text in {"1", "true", "yes", "y"}:
        return True
    try:
        return bool(int(text))
    except Exception:
        return False


def _stress_result_generated_at(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    summary = _coerce_dict(payload.get("summary"))
    generated_at = summary.get("generated_at")
    return str(generated_at) if generated_at is not None else None


def _get_latest_reference_full_matrix_row(
    repo: SupabaseRepo | NoOpSupabaseRepo,
    *,
    limit: int = 12,
) -> dict[str, Any] | None:
    try:
        if hasattr(repo, "get_recent_stress_test_runs"):
            rows = repo.get_recent_stress_test_runs(limit)
            if isinstance(rows, list):
                return _select_preferred_stress_row(rows, artifact_mode=ARTIFACT_MODE_FULL_MATRIX)
        row = repo.get_latest_stress_test_run()
        if isinstance(row, dict) and _stress_row_matches_artifact_mode(row, ARTIFACT_MODE_FULL_MATRIX):
            return row
    except Exception as exc:
        print(f"[abs-modal] failed to load reference full-matrix stress row: {exc}")
    return None


def _build_replay_refresh_status_payload(
    *,
    settings: Settings,
    scope: str,
    status: str,
    start_date: str | None = None,
    end_date: str | None = None,
    requested_at: str | None = None,
    started_at: str | None = None,
    last_refresh_at: str | None = None,
    error: str | None = None,
    existing_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_scope = normalize_replay_scope(scope, settings.abs_replay_scope_default)
    payload = dict(existing_meta or {})
    payload.update(
        {
            "status": status,
            "scope": resolved_scope,
            "scope_tag": replay_scope_tag(resolved_scope),
            "output_csv": replay_output_path(settings, resolved_scope),
        }
    )
    if requested_at is not None:
        payload["requested_at"] = requested_at
    if started_at is not None:
        payload["started_at"] = started_at
    if last_refresh_at is not None:
        payload["last_refresh_at"] = last_refresh_at
    if start_date is not None:
        payload["start_date"] = start_date
    if end_date is not None:
        payload["end_date"] = end_date
    if error is not None or status == "failed":
        payload["error"] = error
    elif status in {"running", "success"}:
        payload.pop("error", None)
    if status == "running":
        payload.pop("catalog_error", None)
    return payload


def _policy_version_fallback(settings: Settings, policy_config: PolicyConfig) -> dict[str, Any]:
    return {
        "version_id": str(settings.abs_policy_version),
        "training_window": "production-bootstrap",
        "assumptions_hash": "unknown",
        "threshold_profile": str(policy_config.profile_name or settings.abs_threshold_profile),
        "deployed_at": STATE.last_retrain_at or _utc_now_iso(),
        "core_model_version": str(settings.abs_core_model_version),
        "execution_model_version": settings.abs_execution_model_version or "none",
        "aptitude_model_version": settings.abs_aptitude_model_version or "none",
    }


def _policy_version_defaults(
    *,
    version_id: str,
    threshold_profile: str,
    settings: Settings,
) -> dict[str, Any]:
    return {
        "version_id": str(version_id),
        "training_window": "production-bootstrap",
        "assumptions_hash": "unknown",
        "threshold_profile": str(threshold_profile),
        "deployed_at": STATE.last_retrain_at or _utc_now_iso(),
        "core_model_version": str(settings.abs_core_model_version),
        "execution_model_version": settings.abs_execution_model_version or "none",
        "aptitude_model_version": settings.abs_aptitude_model_version or "none",
    }


def _merge_missing_dict_values(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in fallback.items():
        current = merged.get(key)
        if key not in merged or current is None or current == "" or current == [] or current == {}:
            merged[key] = value
    return merged


def _log_decision_telemetry_safe(
    repo: SupabaseRepo | NoOpSupabaseRepo,
    payloads: dict[str, Any] | list[dict[str, Any]],
) -> None:
    try:
        if isinstance(payloads, list):
            if not payloads:
                return
            if hasattr(repo, "log_decision_telemetry_batch"):
                repo.log_decision_telemetry_batch(payloads)
            else:
                for payload in payloads:
                    repo.log_decision_telemetry(payload)
            return
        repo.log_decision_telemetry(payloads)
    except Exception as exc:  # pragma: no cover - fail-open observability path
        print(f"[abs-modal] decision telemetry write failed: {exc}")


def _replay_telemetry_outcome(pitch: dict[str, Any]) -> str | None:
    if _coerce_boolish(pitch.get("actual_challenged")):
        return "actual_success" if _coerce_boolish(pitch.get("actual_challenge_correct")) else "actual_fail"
    recommendation = str(pitch.get("recommendation") or "")
    if recommendation == "CHALLENGE":
        return "would_overturn" if _coerce_boolish(pitch.get("overturn_flag")) else "would_fail"
    if recommendation == "HOLD":
        return "hold"
    return None


def _build_replay_decision_telemetry_rows(
    *,
    scope: str,
    active_service: RecommendService,
    game_id: str,
    replay_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    pitch_rows = replay_payload.get("pitches")
    if not isinstance(pitch_rows, list) or not pitch_rows:
        return []

    game_events = [event for event in active_service.events if str(event.game_id) == game_id]
    event_by_pitch_id = {str(event.pitch_id): event for event in game_events}
    rendered_at = _utc_now_iso()
    rows: list[dict[str, Any]] = []

    for index, pitch in enumerate(pitch_rows):
        if not isinstance(pitch, dict):
            continue
        pitch_id = str(pitch.get("pitch_id") or "").strip()
        if not pitch_id:
            continue
        event = event_by_pitch_id.get(pitch_id)
        if event is None:
            continue

        actual_recommendation = pitch.get("actual_recommendation")
        followed_recommendation = None
        if actual_recommendation in {"CHALLENGE", "HOLD"}:
            followed_recommendation = actual_recommendation == pitch.get("recommendation")

        context_snapshot = {
            "telemetry_source": "replay_render",
            "rendered_at": rendered_at,
            "scope": scope,
            "game_id": game_id,
            "pitch_index": index,
            "policy_team": pitch.get("policy_team"),
            "batting_team": pitch.get("batting_team"),
            "fielding_team": pitch.get("fielding_team"),
            "signal_color": pitch.get("signal_color"),
            "challenge_context": {
                "inning": pitch.get("inning"),
                "half": pitch.get("half"),
                "outs": pitch.get("outs"),
                "base_state": pitch.get("base_state"),
                "score_diff": pitch.get("policy_score_diff", pitch.get("score_diff")),
                "count": pitch.get("count"),
                "challenges_left": pitch.get("policy_team_challenges_left", pitch.get("challenges_left")),
                "is_final_challenge": pitch.get("is_final_challenge"),
                "batter_id": getattr(event, "batter_id", None),
                "pitcher_id": getattr(event, "pitcher_id", None),
                "catcher_id": getattr(event, "catcher_id", None),
            },
            "pitch_observation": {
                "px": getattr(event, "px", None),
                "pz": getattr(event, "pz", None),
                "plate_x": pitch.get("plate_x"),
                "plate_z": pitch.get("plate_z"),
                "sz_top": pitch.get("sz_top"),
                "sz_bot": pitch.get("sz_bot"),
                "velo": getattr(event, "velo", None),
                "spin": getattr(event, "spin", None),
                "movement": getattr(event, "movement", None),
                "handedness_matchup": getattr(event, "handedness_matchup", None),
                "call_on_field": pitch.get("call_on_field"),
            },
            "model_outputs": {
                "recommendation": pitch.get("recommendation"),
                "signal_color": pitch.get("signal_color"),
                "confidence": pitch.get("confidence"),
                "p_overturn": pitch.get("p_overturn"),
                "run_swing": pitch.get("run_swing"),
                "net_ev": pitch.get("net_ev"),
                "immediate_ev": pitch.get("immediate_ev"),
                "leverage_adjustment": pitch.get("leverage_adjustment"),
                "opportunity_cost": pitch.get("opportunity_cost"),
                "reason_codes": pitch.get("reason_codes"),
                "top_drivers": pitch.get("top_drivers"),
            },
            "actual": {
                "actual_recommendation": actual_recommendation,
                "actual_challenged": pitch.get("actual_challenged"),
                "actual_challenge_correct": pitch.get("actual_challenge_correct"),
                "actual_challenge_team": pitch.get("actual_challenge_team"),
                "policy_disagrees_with_actual": pitch.get("policy_disagrees_with_actual"),
                "counterfactual_result": pitch.get("counterfactual_result"),
            },
        }
        rows.append(
            {
                "pitch_id": pitch_id,
                "game_id": game_id,
                "recommended_action": pitch.get("recommendation"),
                "recommended_challenger_role": None,
                "model_version": active_service.core_model_version,
                "policy_version": active_service.policy_version,
                "player_action": actual_recommendation,
                "actual_challenger_role": None,
                "outcome": _replay_telemetry_outcome(pitch),
                "followed_recommendation": followed_recommendation,
                "challenge_latency_ms": None,
                "context_snapshot": context_snapshot,
            }
        )
    return rows


def _overlay_dict_values(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if value is not None:
            merged[key] = value
    return merged


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return dict(parsed)
    return {}


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            return datetime.fromisoformat(f"{text}T23:59:59+00:00")
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _source_freshness_hours(value: str | None) -> float | None:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return None
    freshness = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0
    return round(max(0.0, freshness), 3)


def _read_refresh_meta_cached(scope: str, replay_path: str) -> dict[str, Any]:
    cached = STATE.replay_refresh_meta.get(scope)
    if isinstance(cached, dict) and cached.get("output_csv") == replay_path:
        return cached
    loaded = read_replay_refresh_meta(replay_path) or {}
    if isinstance(loaded, dict) and loaded:
        STATE.replay_refresh_meta[scope] = loaded
        return loaded
    return {}


def _augment_model_evaluation_with_runtime_diagnostics(
    model_evaluation: dict[str, Any],
    *,
    settings: Settings,
) -> dict[str, Any]:
    refresh_scope = normalize_replay_scope(settings.abs_replay_scope_default, settings.abs_replay_scope_default)
    refresh_meta = _read_refresh_meta_cached(refresh_scope, replay_output_path(settings, refresh_scope))
    transform_stats = refresh_meta.get("transform_stats") if isinstance(refresh_meta, dict) else {}
    if not isinstance(transform_stats, dict):
        transform_stats = {}
    return _overlay_dict_values(
        model_evaluation,
        {
            "mismatch_reasons": transform_stats.get("skip_reasons") or model_evaluation.get("mismatch_reasons") or {},
            "replay_official_linkage_rate": transform_stats.get("official_match_rate"),
            "source_freshness_hours": _source_freshness_hours(refresh_meta.get("source_max_game_date")),
        },
    )


def _stress_model_evaluation_incomplete(summary: dict[str, Any] | None) -> bool:
    if not isinstance(summary, dict):
        return True
    model_evaluation = summary.get("model_evaluation")
    if not isinstance(model_evaluation, dict):
        return True
    required = (
        "brier_model",
        "brier_baseline",
        "brier_improvement",
        "challenged_pitch_auc",
        "calibration_slope",
        "calibration_intercept",
        "re24_state_drift",
    )
    return any(model_evaluation.get(key) is None for key in required)


def _load_policy_config(settings: Settings) -> PolicyConfig:
    if settings.abs_policy_profile_path:
        try:
            return PolicyConfig.load_json(settings.abs_policy_profile_path)
        except FileNotFoundError:
            print(
                f"[abs-modal] ABS_POLICY_PROFILE_PATH not found: {settings.abs_policy_profile_path}. "
                f"Falling back to ABS_THRESHOLD_PROFILE={settings.abs_threshold_profile!r}."
            )
    return PolicyConfig.from_profile_name(settings.abs_threshold_profile)


def _load_stress_policy_config(settings: Settings) -> PolicyConfig:
    if settings.abs_stress_policy_profile_path:
        try:
            return PolicyConfig.load_json(settings.abs_stress_policy_profile_path)
        except FileNotFoundError:
            print(
                f"[abs-modal] ABS_STRESS_POLICY_PROFILE_PATH not found: {settings.abs_stress_policy_profile_path}. "
                f"Falling back to ABS_STRESS_THRESHOLD_PROFILE={settings.abs_stress_threshold_profile!r}."
            )
    return PolicyConfig.from_profile_name(settings.abs_stress_threshold_profile)


def _policy_config_with_overrides(
    base: PolicyConfig,
    *,
    threshold_profile: str | None = None,
    min_overturn_probability: float | None = None,
    obvious_miss_distance: float | None = None,
) -> PolicyConfig:
    resolved = PolicyConfig.from_profile_name(threshold_profile) if threshold_profile else base
    payload = resolved.to_dict()
    if min_overturn_probability is not None:
        payload["min_overturn_probability"] = min_overturn_probability
    if obvious_miss_distance is not None:
        payload["obvious_miss_distance"] = obvious_miss_distance
    return PolicyConfig.from_dict(payload)


def _build_recommendation_presets(service: RecommendService, limit: int) -> list[dict[str, object]]:
    if not service.events:
        return []

    def parse_game_order(event) -> int:
        try:
            return int(str(event.game_id))
        except Exception:
            return 0

    def parse_pitch_order(event) -> tuple[int, int]:
        pa_num = 0
        pitch_num = 0
        try:
            pa_num = int(str(event.pa_id).split("-")[-1])
        except Exception:
            pa_num = 0
        try:
            pitch_num = int(str(event.pitch_id).split("-")[-1])
        except Exception:
            pitch_num = 0
        return pa_num, pitch_num

    def to_request(event) -> dict[str, object]:
        return {
            "challenge_context": {
                "game_id": event.game_id,
                "inning": event.inning,
                "half": event.half,
                "outs": event.outs,
                "base_state": event.base_state,
                "score_diff": event.score_diff,
                "count": event.count,
                "challenges_left": 1,
                "is_final_challenge": True,
                "batter_id": event.batter_id,
                "pitcher_id": event.pitcher_id,
                "catcher_id": event.catcher_id,
            },
            "pitch_observation": {
                "pitch_id": event.pitch_id,
                "px": event.px,
                "pz": event.pz,
                "plate_x": event.plate_x,
                "plate_z": event.plate_z,
                "sz_top": getattr(event, "sz_top", 3.5),
                "sz_bot": getattr(event, "sz_bot", 1.6),
                "velo": event.velo,
                "spin": event.spin,
                "movement": event.movement,
                "handedness_matchup": event.handedness_matchup,
                "call_on_field": event.call_on_field,
            },
            "model_version": "v1",
        }

    ordered = sorted(
        service.events,
        key=lambda e: (parse_game_order(e), e.inning, 0 if e.half == "top" else 1, *parse_pitch_order(e)),
    )
    most_recent = ordered[-1]
    presets = [
        {
            "id": f"most-recent-{most_recent.pitch_id}",
            "label": (
                f"Most Recent {service.data_source_mode.title()} Pitch - G{most_recent.game_id} "
                f"{most_recent.half} {most_recent.inning}, {most_recent.count}"
            ),
            "source": service.data_source_mode,
            "is_most_recent": True,
            "request": to_request(most_recent),
            "updated_at": _utc_now_iso(),
        }
    ]

    seen_pitch_ids = {most_recent.pitch_id}
    for event in sorted(service.events, key=_replay_leverage_score, reverse=True):
        if len(presets) >= max(2, limit):
            break
        if event.pitch_id in seen_pitch_ids:
            continue
        seen_pitch_ids.add(event.pitch_id)
        presets.append(
            {
                "id": f"hl-{event.pitch_id}",
                "label": (
                    f"High-Leverage - G{event.game_id} {event.half} {event.inning}, "
                    f"{event.count}, base {event.base_state}, diff {event.score_diff:+d}"
                ),
                "source": service.data_source_mode,
                "is_most_recent": False,
                "request": to_request(event),
                "updated_at": _utc_now_iso(),
            }
        )
    return presets[:limit]


def _replay_leverage_score(event) -> float:
    score = 0.0
    if event.count in {"3-2", "3-1", "2-2", "0-2"}:
        score += 2.5
    if event.inning >= 7:
        score += 2.0
    if abs(event.score_diff) <= 1:
        score += 1.8
    score += 0.9 * event.base_state.count("1")
    return score


def _replay_leverage_bucket(score: float) -> str:
    if score >= 5.0:
        return "HIGH"
    if score >= 1.5:
        return "ELEVATED"
    return "ROUTINE"


def _replay_zone_distance_to_edge(plate_x: float, plate_z: float, sz_bot: float = 1.6, sz_top: float = 3.5) -> float:
    horizontal_gap = max(0.0, abs(plate_x) - 0.83)
    if plate_z < sz_bot:
        vertical_gap = sz_bot - plate_z
    elif plate_z > sz_top:
        vertical_gap = plate_z - sz_top
    else:
        vertical_gap = 0.0
    return max(horizontal_gap, vertical_gap)


def _event_zone_bounds(event: Any) -> tuple[float, float]:
    sz_top = float(getattr(event, "sz_top", 3.5) or 3.5)
    sz_bot = float(getattr(event, "sz_bot", 1.6) or 1.6)
    return sz_top, sz_bot


def _teams_for_half(half: str, home_team: str, away_team: str) -> tuple[str, str]:
    batting_team = away_team if half == "top" else home_team
    fielding_team = home_team if half == "top" else away_team
    return batting_team, fielding_team


def _eligible_team_for_pitch(call_on_field: str, half: str, home_team: str, away_team: str) -> str:
    batting_team, fielding_team = _teams_for_half(half, home_team, away_team)
    return fielding_team if call_on_field == "ball" else batting_team


def _normalize_replay_team(raw_team: str | None, home_team: str, away_team: str) -> str | None:
    value = str(raw_team or "").strip().upper()
    if not value:
        return None
    if value in {home_team.upper(), away_team.upper()}:
        return home_team if value == home_team.upper() else away_team
    if value in {"HOME", "H"}:
        return home_team
    if value in {"AWAY", "A"}:
        return away_team
    return None


def _resolve_replay_policy_team(policy_team: str | None, home_team: str, away_team: str) -> str | None:
    if policy_team is None:
        return None
    normalized = _normalize_replay_team(policy_team, home_team, away_team)
    if normalized is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid policy_team '{policy_team}'. Expected one of {home_team}, {away_team}, HOME, or AWAY.",
        )
    return normalized


def _policy_team_for_pitch(call_on_field: str, half: str, home_team: str, away_team: str) -> str:
    return _eligible_team_for_pitch(call_on_field, half, home_team, away_team)


def _score_diff_for_selected_team(raw_score_diff: int, selected_team: str, batting_team: str, fielding_team: str) -> int:
    return raw_score_diff if selected_team == batting_team else -raw_score_diff


def _score_diff_for_policy_team(raw_score_diff: int, call_on_field: str) -> int:
    return -raw_score_diff if call_on_field == "ball" else raw_score_diff


def _describe_score_state(score_diff: int) -> str:
    if score_diff > 0:
        return f"Policy team leading by {score_diff}"
    if score_diff < 0:
        return f"Policy team trailing by {abs(score_diff)}"
    return "Game tied for the policy team"


_REPLAY_DRIVER_MAP = {
    "LOW_OVERTURN_PROBABILITY_FLOOR": "Overturn odds are below the minimum threshold.",
    "PRESERVE_CHALLENGE_VALUE": "Save challenge inventory for better later opportunities.",
    "HIGH_LEVERAGE_STATE": "Late/high-value game state raises challenge value.",
    "CRITICAL_COUNT": "The count makes the pitch more consequential than routine states.",
    "FINAL_CHALLENGE_NO_CONTINUATION": "This is the last available challenge, so inventory value matters more.",
    "POSITIVE_NET_EV": "The challenge clears the current expected-value threshold.",
    "LOCATION_SANITY_GUARDRAIL": "Pitch location is too far from the zone for a confident challenge.",
    "UNCERTAINTY_GUARDRAIL": "Model uncertainty is too high for the current edge.",
    "NO_CHALLENGES_LEFT": "No challenges remain for the policy team.",
    "POLICY_TEAM_NOT_ELIGIBLE": "Selected policy team is not eligible to challenge this pitch.",
}


def _policy_team_not_eligible_response(policy_response: RecommendationResponse) -> RecommendationResponse:
    top_drivers = _top_drivers_from_reason_codes(
        ["POLICY_TEAM_NOT_ELIGIBLE"],
        overturn_probability=policy_response.p_overturn,
        base_state="000",
        score_diff=0,
    )
    return RecommendationResponse(
        recommendation=Recommendation.HOLD,
        confidence=policy_response.confidence,
        expected_runs_gained=0.0,
        future_option_cost=0.0,
        net_ev=0.0,
        p_overturn=policy_response.p_overturn,
        run_swing=policy_response.run_swing,
        immediate_overturn_ev=0.0,
        state_leverage_adjustment=0.0,
        opportunity_cost=0.0,
        challenge_ev=0.0,
        reason_codes=["POLICY_TEAM_NOT_ELIGIBLE"],
        top_drivers=top_drivers,
        core_model_version=policy_response.core_model_version,
        policy_version=policy_response.policy_version,
        execution_model_version=policy_response.execution_model_version,
        aptitude_model_version=policy_response.aptitude_model_version,
        execution_adjusted_ev=policy_response.execution_adjusted_ev,
        recommended_challenger_role=policy_response.recommended_challenger_role,
        latency_ms=policy_response.latency_ms,
    )


def _top_drivers_from_reason_codes(reason_codes: list[str], overturn_probability: float, base_state: str, score_diff: int) -> list[str]:
    drivers: list[str] = []
    for code in reason_codes:
        label = _REPLAY_DRIVER_MAP.get(code)
        if label and label not in drivers:
            drivers.append(label)
    if overturn_probability >= 0.20 and len(drivers) < 3:
        drivers.append("Overturn probability is meaningfully above the floor.")
    if base_state != "000" and len(drivers) < 3:
        drivers.append("Base runners raise the value of getting the call right.")
    if abs(score_diff) <= 1 and len(drivers) < 3:
        drivers.append("Close score keeps the decision valuable from the policy-team perspective.")
    return drivers[:3]


def _run_and_cache_stress_test(
    policy_config: PolicyConfig,
    policy_version_id: str,
    threshold_profile: str,
    settings: Settings,
    repo: SupabaseRepo | NoOpSupabaseRepo,
    sims: int,
    seed: int,
    pitch_events_csv_path: str | None,
    artifact_mode: str = ARTIFACT_MODE_FULL_MATRIX,
    reference_full_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_path = pitch_events_csv_path or settings.pitch_events_csv_path or settings.abs_production_pitch_events_path
    if not effective_path:
        raise HTTPException(status_code=400, detail="PITCH_EVENTS_CSV_PATH is required for production stress tests")

    payload, memo_markdown, memo_assumption_warnings, summary_for_storage = generate_stress_test_artifacts(
        pitch_events_csv_path=effective_path,
        policy_config=policy_config,
        policy_version_id=policy_version_id,
        threshold_profile=threshold_profile,
        sims=sims,
        seed=seed,
        artifact_mode=artifact_mode,
        scenario_names=(["base"] if artifact_mode == ARTIFACT_MODE_FAST_BASE else None),
        reference_full_row=reference_full_row,
        core_model_version=settings.abs_core_model_version,
        execution_model_version=settings.abs_execution_model_version,
        aptitude_model_version=settings.abs_aptitude_model_version,
    )

    def _augment_stress_summary(payload_summary: dict[str, Any]) -> None:
        if not isinstance(payload_summary, dict):
            return
        policy_version = payload_summary.get("policy_version") or {}
        payload_summary["policy_version"] = _merge_missing_dict_values(
            policy_version if isinstance(policy_version, dict) else {},
            _policy_version_defaults(
                version_id=policy_version_id,
                threshold_profile=threshold_profile,
                settings=settings,
            ),
        )
        model_evaluation = payload_summary.get("model_evaluation") or {}
        if not isinstance(model_evaluation, dict):
            model_evaluation = {}
        refresh_meta = _read_refresh_meta_cached(
            normalize_replay_scope(settings.abs_replay_scope_default, settings.abs_replay_scope_default),
            replay_output_path(settings, normalize_replay_scope(settings.abs_replay_scope_default, settings.abs_replay_scope_default)),
        )
        transform_stats = refresh_meta.get("transform_stats") if isinstance(refresh_meta, dict) else {}
        if not isinstance(transform_stats, dict):
            transform_stats = {}
        diagnostics = {
            "re24_state_drift": model_evaluation.get("re24_state_drift"),
            "mismatch_reasons": transform_stats.get("skip_reasons") or model_evaluation.get("mismatch_reasons") or {},
            "replay_official_linkage_rate": transform_stats.get("official_match_rate"),
            "source_freshness_hours": _source_freshness_hours(refresh_meta.get("source_max_game_date")),
        }
        payload_summary["model_evaluation"] = _merge_missing_dict_values(model_evaluation, diagnostics)

    _augment_stress_summary(payload.get("summary") or {})
    _augment_stress_summary(summary_for_storage)

    now_iso = _utc_now_iso()
    STATE.latest_result = payload
    STATE.last_ingest_at = now_iso
    STATE.last_retrain_at = now_iso
    STATE.last_stress_test_at = now_iso
    print(
        f"[abs-modal] stress artifact completed mode={artifact_mode} sims={sims} seed={seed} "
        f"generated_at={_stress_result_generated_at(payload)}"
    )

    STATE.latest_memo = memo_markdown
    STATE.latest_memo_assumption_warnings = memo_assumption_warnings

    try:
        repo.upsert_model_version(
            build_model_version_row(
                payload=payload,
                version_id=policy_version_id,
                threshold_profile=threshold_profile,
            )
        )
        repo.write_stress_test_run(
            build_stress_test_row(
                payload=payload,
                summary_for_storage=summary_for_storage,
                sims=sims,
                seed=seed,
                model_version_id=policy_version_id,
                data_source_mode="production",
            )
        )
    except Exception as exc:
        # Keep API responsive even if telemetry write fails, but surface the
        # failure in logs so persistence issues do not stay silent.
        print(f"[abs-modal] failed to persist stress artifacts: {exc}")

    _set_recompute_status(
        artifact_mode,
        status="completed",
        completed_at=now_iso,
        latest_generated_at=_stress_result_generated_at(payload),
    )
    return payload


def _refresh_and_persist_model_evaluation_artifacts(
    *,
    active_policy_version: str,
    active_threshold_profile: str,
    pitch_events_csv_path: str | None,
    settings: Settings,
    repo: SupabaseRepo | NoOpSupabaseRepo,
) -> dict[str, Any]:
    effective_path = pitch_events_csv_path or settings.pitch_events_csv_path or settings.abs_production_pitch_events_path
    if not effective_path:
        raise RuntimeError("PITCH_EVENTS_CSV_PATH is required for model evaluation refresh")

    model_evaluation = generate_model_evaluation_artifact(pitch_events_csv_path=effective_path)
    model_evaluation = _augment_model_evaluation_with_runtime_diagnostics(model_evaluation, settings=settings)

    policy_defaults = _policy_version_defaults(
        version_id=active_policy_version,
        threshold_profile=active_threshold_profile,
        settings=settings,
    )
    now_iso = _utc_now_iso()
    model_version_row = build_model_version_row(
        payload={
            "generated_at": now_iso,
            "summary": {
                "policy_version": policy_defaults,
                "model_evaluation": model_evaluation,
            },
        },
        version_id=active_policy_version,
        threshold_profile=active_threshold_profile,
    )
    try:
        repo.upsert_model_version(model_version_row)
    except Exception as exc:
        print(f"[abs-modal] failed to upsert model-version artifact: {exc}")

    latest_row = None
    try:
        if hasattr(repo, "get_recent_stress_test_runs"):
            rows = repo.get_recent_stress_test_runs(8)
            if isinstance(rows, list):
                latest_row = _select_preferred_stress_row(rows)
        if latest_row is None:
            row = repo.get_latest_stress_test_run()
            if isinstance(row, dict):
                latest_row = row
    except Exception as exc:
        print(f"[abs-modal] failed to load latest stress row for model evaluation refresh: {exc}")

    if isinstance(latest_row, dict):
        current_summary = _coerce_dict(latest_row.get("summary"))
        current_policy_version = _coerce_dict(current_summary.get("policy_version"))
        current_summary["policy_version"] = _merge_missing_dict_values(current_policy_version, policy_defaults)
        current_model_evaluation = _coerce_dict(current_summary.get("model_evaluation"))
        current_summary["model_evaluation"] = _overlay_dict_values(current_model_evaluation, model_evaluation)
        try:
            run_at = latest_row.get("run_at")
            if run_at is not None:
                repo.update_stress_test_run_summary(str(run_at), current_summary)
        except Exception as exc:
            print(f"[abs-modal] failed to update latest stress summary with model evaluation: {exc}")
        if isinstance(STATE.latest_result, dict):
            cached_summary = _coerce_dict(STATE.latest_result.get("summary"))
            cached_summary["policy_version"] = _merge_missing_dict_values(
                _coerce_dict(cached_summary.get("policy_version")),
                policy_defaults,
            )
            cached_summary["model_evaluation"] = _overlay_dict_values(
                _coerce_dict(cached_summary.get("model_evaluation")),
                model_evaluation,
            )
            STATE.latest_result["summary"] = cached_summary

    _set_model_evaluation_status(
        status="completed",
        completed_at=_utc_now_iso(),
    )
    return model_evaluation


def _result_from_stored_row(
    row: dict[str, Any],
    *,
    repo: SupabaseRepo | NoOpSupabaseRepo,
    settings: Settings,
    stress_policy_config: PolicyConfig,
) -> dict[str, Any]:
    summary = _coerce_dict(row.get("summary"))
    policy_version = _coerce_dict(summary.get("policy_version"))
    model_version_id = (
        row.get("model_version_id")
        or policy_version.get("version_id")
        or settings.abs_stress_policy_version
    )
    model_version_row: dict[str, Any] | None = None
    try:
        if model_version_id:
            model_version_row = repo.get_model_version(str(model_version_id))
    except Exception:
        model_version_row = None

    policy_defaults = _policy_version_defaults(
        version_id=str(model_version_id or settings.abs_stress_policy_version),
        threshold_profile=(
            str(policy_version.get("threshold_profile") or stress_policy_config.profile_name or settings.abs_stress_threshold_profile)
        ),
        settings=settings,
    )
    if isinstance(model_version_row, dict):
        policy_defaults = _merge_missing_dict_values(
            policy_defaults,
            {
                "training_window": model_version_row.get("training_window"),
                "assumptions_hash": model_version_row.get("assumptions_hash"),
                "threshold_profile": model_version_row.get("threshold_profile"),
                "deployed_at": str(model_version_row.get("deployed_at")) if model_version_row.get("deployed_at") else None,
                "core_model_version": model_version_row.get("core_model_version"),
                "execution_model_version": model_version_row.get("execution_model_version"),
                "aptitude_model_version": model_version_row.get("aptitude_model_version"),
            },
        )
    summary["policy_version"] = _merge_missing_dict_values(policy_version, policy_defaults)

    metadata = _coerce_dict(model_version_row.get("metadata")) if isinstance(model_version_row, dict) else {}
    metadata_model_eval = _coerce_dict(metadata.get("model_evaluation"))
    current_model_eval = _coerce_dict(summary.get("model_evaluation"))
    refresh_scope = normalize_replay_scope(settings.abs_replay_scope_default, settings.abs_replay_scope_default)
    refresh_meta = _read_refresh_meta_cached(refresh_scope, replay_output_path(settings, refresh_scope))
    transform_stats = refresh_meta.get("transform_stats") if isinstance(refresh_meta, dict) else {}
    if not isinstance(transform_stats, dict):
        transform_stats = {}
    summary["model_evaluation"] = _merge_missing_dict_values(
        _merge_missing_dict_values(current_model_eval, metadata_model_eval),
        {
            "mismatch_reasons": transform_stats.get("skip_reasons") or {},
            "replay_official_linkage_rate": transform_stats.get("official_match_rate"),
            "source_freshness_hours": _source_freshness_hours(refresh_meta.get("source_max_game_date")),
        },
    )

    return {
        "summary": summary,
        "go_decision": row.get("go_decision") or "UNKNOWN",
        "rationale": row.get("rationale") or [],
        "criteria": row.get("criteria") or {},
        "top_aptitudes": row.get("top_aptitudes") or summary.get("top_aptitudes") or [],
        "run_impact_by_player": row.get("run_impact_by_player") or summary.get("run_impact_by_player") or {},
        "confidence_interval_low": row.get("confidence_interval_low"),
        "confidence_interval_high": row.get("confidence_interval_high"),
        "data_window_start": summary.get("data_window_start"),
        "data_window_end": summary.get("data_window_end"),
        "drift_flag": row.get("drift_flag"),
        "assumption_warnings": row.get("assumption_warnings") or [],
    }


def _hydrate_cached_ui_artifacts_from_row(row: dict[str, Any]) -> None:
    summary = _coerce_dict(row.get("summary"))
    memo_markdown = summary.get("memo_markdown")
    if isinstance(memo_markdown, str) and memo_markdown.strip():
        STATE.latest_memo = memo_markdown
    warnings = summary.get("memo_assumption_warnings")
    if isinstance(warnings, list):
        STATE.latest_memo_assumption_warnings = [str(item) for item in warnings if item is not None]


def build_fastapi_app() -> FastAPI:
    settings = load_settings()
    policy_config = _load_policy_config(settings)
    stress_policy_config = _load_stress_policy_config(settings)
    service: RecommendService | None = None
    service_init_error: str | None = None
    try:
        service = RecommendService(
            pitch_events_csv_path=settings.pitch_events_csv_path or settings.abs_production_pitch_events_path,
            policy_config=policy_config,
            threshold_profile=settings.abs_threshold_profile,
            core_model_version=settings.abs_core_model_version,
            policy_version=settings.abs_policy_version,
            execution_model_version=settings.abs_execution_model_version,
            aptitude_model_version=settings.abs_aptitude_model_version,
        )
    except Exception as exc:
        service_init_error = str(exc)
        print(f"[abs-modal] RecommendService initialization failed: {exc}")

    repo = _build_repo(settings)
    supabase_client = getattr(repo, "client", None)
    api = FastAPI(title="ABS Challenge API (Modal)", redirect_slashes=False)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.get("/v1/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "abs-challenge-api",
            "version": "v1",
            "supabase_enabled": not settings.disable_supabase,
            "model_ready": service is not None,
            "model_error": service_init_error,
            "build_id": BUILD_ID,
        }

    @api.get("/v1/debug/routes")
    def debug_routes() -> dict[str, object]:
        routes = []
        for route in api.routes:
            path = getattr(route, "path", "")
            methods = sorted(list(getattr(route, "methods", [])))
            if path.startswith("/v1/"):
                routes.append({"path": path, "methods": methods})
        return {"build_id": BUILD_ID, "routes": routes}

    @api.get("/v1/policy/version")
    def policy_version() -> dict[str, str]:
        if STATE.latest_result:
            version = STATE.latest_result["summary"].get("policy_version")
            if version:
                return version
        try:
            row = repo.get_model_version(settings.abs_policy_version)
            if row:
                deployed_at = row.get("deployed_at")
                return {
                    "version_id": str(row.get("version_id", settings.abs_policy_version)),
                    "training_window": str(row.get("training_window", "production-bootstrap")),
                    "assumptions_hash": str(row.get("assumptions_hash", "unknown")),
                    "threshold_profile": str(row.get("threshold_profile", settings.abs_threshold_profile)),
                    "deployed_at": str(deployed_at) if deployed_at is not None else _utc_now_iso(),
                    "core_model_version": str(row.get("core_model_version", settings.abs_core_model_version)),
                    "execution_model_version": str(row.get("execution_model_version") or settings.abs_execution_model_version or "none"),
                    "aptitude_model_version": str(row.get("aptitude_model_version") or settings.abs_aptitude_model_version or "none"),
                }
        except Exception:
            pass
        return _policy_version_fallback(settings, policy_config)

    def _require_service() -> RecommendService:
        if service is None:
            detail = service_init_error or "Production recommendation model unavailable"
            raise HTTPException(status_code=503, detail=detail)
        return service

    def _safe_int_token(value: str | None) -> int:
        token = (value or "").strip()
        if not token:
            return 0
        if token.isdigit():
            return int(token)
        digits = "".join(ch for ch in token if ch.isdigit())
        return int(digits) if digits else 0

    def _require_replay_share(grant_id: str, *, active_only: bool = True) -> dict[str, Any]:
        record = get_pitching_replay_share_grant(grant_id)
        if not isinstance(record, dict):
            raise HTTPException(status_code=404, detail="Replay share not found")
        if active_only and not is_pitching_replay_share_active(record):
            raise HTTPException(status_code=410, detail="Replay share expired")
        return record

    def _require_supabase_auth_client() -> Any:
        if settings.disable_supabase or supabase_client is None:
            raise HTTPException(status_code=503, detail="Secure replay access is not configured")
        return supabase_client

    def _extract_bearer_token(request: Request) -> str:
        auth_header = str(request.headers.get("authorization") or "").strip()
        if not auth_header.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Sign in required")
        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            raise HTTPException(status_code=401, detail="Sign in required")
        return token

    def _authenticated_email(request: Request) -> str:
        client = _require_supabase_auth_client()
        token = _extract_bearer_token(request)
        try:
            response = client.auth.get_user(token)
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Invalid session: {exc}") from exc
        user = getattr(response, "user", None)
        email = normalize_email(getattr(user, "email", None) if user is not None else None)
        if not email and isinstance(response, dict):
            user_dict = response.get("user") or {}
            email = normalize_email(user_dict.get("email"))
        if not email:
            raise HTTPException(status_code=401, detail="Unable to resolve signed-in email")
        return email

    def _authenticated_user(request: Request) -> dict[str, Any]:
        client = _require_supabase_auth_client()
        token = _extract_bearer_token(request)
        try:
            response = client.auth.get_user(token)
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Invalid session: {exc}") from exc
        user = getattr(response, "user", None)
        if user is None and isinstance(response, dict):
            user = response.get("user")
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in required")
        user_id = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
        email = normalize_email(
            getattr(user, "email", None) if not isinstance(user, dict) else user.get("email")
        )
        if not user_id:
            raise HTTPException(status_code=401, detail="Unable to resolve signed-in user id")
        return {"id": str(user_id), "email": email}

    def _require_admin_caller(request: Request) -> dict[str, Any]:
        if supabase_client is None:
            raise HTTPException(status_code=503, detail="Auth backend not configured")
        caller = _authenticated_user(request)
        try:
            response = (
                supabase_client.table("profiles")
                .select("user_id, role, full_name")
                .eq("user_id", caller["id"])
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to load profile: {exc}") from exc
        row = getattr(response, "data", None)
        if not row or str(row.get("role") or "").lower() != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        return {**caller, "profile": row}

    def _list_admin_users() -> list[dict[str, Any]]:
        if supabase_client is None:
            raise HTTPException(status_code=503, detail="Auth backend not configured")
        try:
            profiles_resp = (
                supabase_client.table("profiles")
                .select("user_id, role, full_name, created_at")
                .execute()
            )
            memberships_resp = (
                supabase_client.table("team_memberships")
                .select("user_id, team_abbr")
                .execute()
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read profiles: {exc}") from exc
        profile_rows = getattr(profiles_resp, "data", None) or []
        membership_rows = getattr(memberships_resp, "data", None) or []
        teams_by_user: dict[str, list[str]] = {}
        for row in membership_rows:
            uid = str(row.get("user_id") or "")
            team_abbr = str(row.get("team_abbr") or "").upper()
            if not uid or not team_abbr:
                continue
            teams_by_user.setdefault(uid, []).append(team_abbr)
        for uid in teams_by_user:
            teams_by_user[uid] = sorted(set(teams_by_user[uid]))
        try:
            auth_resp = supabase_client.auth.admin.list_users()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to list auth users: {exc}") from exc
        emails_by_user: dict[str, str] = {}
        users_iter = getattr(auth_resp, "users", None) or (
            auth_resp.get("users") if isinstance(auth_resp, dict) else None
        ) or auth_resp
        for user in users_iter or []:
            uid = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
            email = normalize_email(
                getattr(user, "email", None) if not isinstance(user, dict) else user.get("email")
            )
            if uid:
                emails_by_user[str(uid)] = email or ""
        users: list[dict[str, Any]] = []
        for row in profile_rows:
            uid = str(row.get("user_id") or "")
            if not uid:
                continue
            users.append(
                {
                    "user_id": uid,
                    "email": emails_by_user.get(uid, ""),
                    "role": str(row.get("role") or "viewer"),
                    "full_name": row.get("full_name"),
                    "team_abbrs": teams_by_user.get(uid, []),
                    "created_at": row.get("created_at"),
                }
            )
        users.sort(key=lambda r: (r.get("role") != "admin", (r.get("email") or "").lower()))
        return users

    def _sync_team_memberships(user_id: str, team_abbrs: list[str], granted_by: str | None) -> None:
        if supabase_client is None:
            raise HTTPException(status_code=503, detail="Auth backend not configured")
        desired = sorted({str(value).upper() for value in (team_abbrs or []) if value})
        try:
            current_resp = (
                supabase_client.table("team_memberships")
                .select("team_abbr")
                .eq("user_id", user_id)
                .execute()
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read memberships: {exc}") from exc
        current = {
            str(row.get("team_abbr") or "").upper()
            for row in (getattr(current_resp, "data", None) or [])
            if row.get("team_abbr")
        }
        desired_set = set(desired)
        to_remove = sorted(current - desired_set)
        to_add = sorted(desired_set - current)
        if to_remove:
            try:
                (
                    supabase_client.table("team_memberships")
                    .delete()
                    .eq("user_id", user_id)
                    .in_("team_abbr", to_remove)
                    .execute()
                )
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to revoke teams: {exc}") from exc
        if to_add:
            rows = [
                {"user_id": user_id, "team_abbr": abbr, "granted_by": granted_by}
                for abbr in to_add
            ]
            try:
                supabase_client.table("team_memberships").insert(rows).execute()
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to grant teams: {exc}") from exc

    @api.get("/v1/admin/users")
    def list_admin_users(request: Request) -> dict[str, Any]:
        _require_admin_caller(request)
        return {"users": _list_admin_users()}

    @api.post("/v1/admin/users/invite")
    async def invite_admin_user(request: Request) -> dict[str, Any]:
        admin = _require_admin_caller(request)
        if supabase_client is None:
            raise HTTPException(status_code=503, detail="Auth backend not configured")
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        email = normalize_email((body or {}).get("email") or "")
        role = str((body or {}).get("role") or "viewer").lower().strip()
        team_abbrs = list((body or {}).get("team_abbrs") or [])
        full_name = (body or {}).get("full_name")
        if not email:
            raise HTTPException(status_code=422, detail="email is required")
        if role not in {"admin", "viewer"}:
            raise HTTPException(status_code=422, detail="role must be 'admin' or 'viewer'")
        try:
            invite_resp = supabase_client.auth.admin.invite_user_by_email(email)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to invite user: {exc}") from exc
        invited_user = getattr(invite_resp, "user", None) or (
            invite_resp.get("user") if isinstance(invite_resp, dict) else None
        )
        invited_id = (
            getattr(invited_user, "id", None)
            if invited_user is not None and not isinstance(invited_user, dict)
            else (invited_user or {}).get("id") if isinstance(invited_user, dict) else None
        )
        if not invited_id:
            raise HTTPException(status_code=500, detail="Invite succeeded but user_id was not returned")
        invited_id = str(invited_id)
        try:
            supabase_client.table("profiles").upsert(
                {
                    "user_id": invited_id,
                    "role": role,
                    "full_name": full_name,
                    "updated_at": _utc_now_iso(),
                },
                on_conflict="user_id",
            ).execute()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to write profile: {exc}") from exc
        _sync_team_memberships(invited_id, team_abbrs, granted_by=admin["id"])
        return {
            "user": {
                "user_id": invited_id,
                "email": email,
                "role": role,
                "full_name": full_name,
                "team_abbrs": sorted({str(value).upper() for value in team_abbrs if value}),
            }
        }

    @api.put("/v1/admin/users/{user_id}")
    async def update_admin_user(user_id: str, request: Request) -> dict[str, Any]:
        admin = _require_admin_caller(request)
        if supabase_client is None:
            raise HTTPException(status_code=503, detail="Auth backend not configured")
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        target_id = str(user_id or "").strip()
        if not target_id:
            raise HTTPException(status_code=422, detail="user_id is required")
        role = (body or {}).get("role")
        full_name = (body or {}).get("full_name")
        team_abbrs = (body or {}).get("team_abbrs")
        if role is not None:
            normalized_role = str(role).lower().strip()
            if normalized_role not in {"admin", "viewer"}:
                raise HTTPException(status_code=422, detail="role must be 'admin' or 'viewer'")
            if target_id == admin["id"] and normalized_role != "admin":
                raise HTTPException(status_code=422, detail="You cannot demote your own admin role")
        else:
            normalized_role = None
        update_payload: dict[str, Any] = {"updated_at": _utc_now_iso()}
        if normalized_role is not None:
            update_payload["role"] = normalized_role
        if full_name is not None:
            update_payload["full_name"] = full_name
        if normalized_role is not None or full_name is not None:
            try:
                supabase_client.table("profiles").update(update_payload).eq("user_id", target_id).execute()
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to update profile: {exc}") from exc
        if team_abbrs is not None:
            _sync_team_memberships(target_id, list(team_abbrs), granted_by=admin["id"])
        return {"ok": True, "user_id": target_id}

    @api.delete("/v1/admin/users/{user_id}")
    def delete_admin_user(user_id: str, request: Request) -> dict[str, Any]:
        admin = _require_admin_caller(request)
        if supabase_client is None:
            raise HTTPException(status_code=503, detail="Auth backend not configured")
        target_id = str(user_id or "").strip()
        if not target_id:
            raise HTTPException(status_code=422, detail="user_id is required")
        if target_id == admin["id"]:
            raise HTTPException(status_code=422, detail="You cannot delete your own account")
        try:
            supabase_client.auth.admin.delete_user(target_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to delete auth user: {exc}") from exc
        return {"ok": True, "user_id": target_id}

    def _send_replay_share_login_email(record: dict[str, Any]) -> None:
        client = _require_supabase_auth_client()
        recipient_email = normalize_email(record.get("recipient_email"))
        if not recipient_email:
            raise HTTPException(status_code=500, detail="Replay share recipient is missing")
        redirect_to = build_pitching_replay_share_url(str(record.get("grant_id") or ""), BRAIN_APP_BASE_URL)
        try:
            client.auth.sign_in_with_otp(
                {
                    "email": recipient_email,
                    "options": {
                        "email_redirect_to": redirect_to,
                        "should_create_user": True,
                    },
                }
            )
        except Exception as exc:
            message = str(exc)
            invite_blocked = any(
                token in message.lower()
                for token in ("signup", "signups", "invite", "user not allowed", "disabled")
            )
            if not invite_blocked:
                raise HTTPException(status_code=400, detail=f"Unable to send secure access link: {exc}") from exc
            try:
                client.auth.admin.invite_user_by_email(
                    recipient_email,
                    {"redirect_to": redirect_to},
                )
            except Exception as invite_exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to send secure access link: {invite_exc}",
                ) from invite_exc

    def _to_int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except Exception:
            return default

    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    def _pitch_sort_key(event: Any) -> tuple[int, int, int, int]:
        pa_num = _safe_int_token(str(getattr(event, "pa_id", "")).split("-")[-1])
        pitch_num = _safe_int_token(str(getattr(event, "pitch_id", "")).split("-")[-1])
        half_order = 0 if getattr(event, "half", "top") == "top" else 1
        inning = int(getattr(event, "inning", 0))
        return (inning, half_order, pa_num, pitch_num)

    def _signal_to_color(signal: str | None) -> str:
        normalized = (signal or "").strip().upper()
        if normalized == "GREEN":
            return "GREEN"
        if normalized == "YELLOW":
            return "YELLOW"
        return "GRAY"

    def _resolve_replay_scope(scope: str | None) -> str:
        return normalize_replay_scope(scope, settings.abs_replay_scope_default)

    def _replay_csv_path(scope: str) -> str:
        return replay_output_path(settings, scope)

    def _invalidate_replay_caches(scope: str | None = None) -> None:
        if scope is None:
            STATE.replay_games_cache.clear()
            STATE.replay_payload_cache.clear()
            STATE.replay_game_stats_cache.clear()
            STATE.replay_catalog_cache.clear()
            STATE.replay_dataset_stats_cache.clear()
            STATE.replay_services.clear()
            STATE.replay_service_paths.clear()
            STATE.official_challenge_counts_by_game = None
            return
        STATE.replay_games_cache.pop(scope, None)
        STATE.replay_payload_cache.pop(scope, None)
        STATE.replay_game_stats_cache.pop(scope, None)
        STATE.replay_catalog_cache.pop(scope, None)
        STATE.replay_dataset_stats_cache.pop(scope, None)
        STATE.replay_services.pop(scope, None)
        STATE.replay_service_paths.pop(scope, None)
        STATE.official_challenge_counts_by_game = None

    class _OptimisticCounts(dict):
        """Returned when challenge_events.csv is absent.

        The current data-sync pipeline does not generate challenge_events.csv, so
        the file is never present on a fresh container. Returning a positive count
        for every game_id prevents the "actual_challenges_in_source > 0 and
        official_actual_challenges_in_source == 0" suppression from firing when the
        file simply hasn't been built — not because the game has no official data.
        """

        def get(self, key: Any, default: Any = 0) -> Any:  # noqa: D102
            return 1

    def _load_official_challenge_counts_by_game() -> dict[str, int]:
        cached = STATE.official_challenge_counts_by_game
        if cached is not None:
            return cached

        challenge_path = Path(settings.abs_challenge_events_path)
        if not challenge_path.exists():
            # File is not generated by the current pipeline. Return an optimistic
            # sentinel so that replay metrics are not suppressed solely due to a
            # missing file — the replay CSV itself comes from official Statcast data.
            result: dict[str, int] = _OptimisticCounts()  # type: ignore[assignment]
            STATE.official_challenge_counts_by_game = result
            return result

        counts: dict[str, int] = {}
        with challenge_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                gid = str(row.get("game_id", "")).strip()
                if not gid:
                    continue
                counts[gid] = counts.get(gid, 0) + 1
        STATE.official_challenge_counts_by_game = counts
        return counts

    def _ensure_replay_dataset_exists(scope: str) -> str:
        resolved_scope = _resolve_replay_scope(scope)
        replay_path = _replay_csv_path(resolved_scope)
        if Path(replay_path).exists():
            return replay_path
        if resolved_scope != "abs_only":
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Replay source file not found for scope={resolved_scope}: {replay_path}. "
                    "Run POST /v1/replay/refresh to build it."
                ),
            )
        # Try downloading the pre-built replay CSV from Supabase (~60 MB) before
        # falling back to a full background rebuild (~600 MB, takes hours).
        print(f"[abs-modal] replay dataset missing, abs_replay_output_uri={settings.abs_replay_output_uri!r}")
        if settings.abs_replay_output_uri:
            try:
                import os as _os
                import shutil as _shutil
                Path(replay_path).parent.mkdir(parents=True, exist_ok=True)
                print(f"[abs-modal] downloading pre-built replay CSV from {settings.abs_replay_output_uri}")
                req_dl = UrlRequest(
                    settings.abs_replay_output_uri,
                    method="GET",
                    headers={"User-Agent": "the-brain-abs/1.0"},
                )
                with urlopen(req_dl, timeout=300) as resp, open(replay_path, "wb") as out_f:
                    _shutil.copyfileobj(resp, out_f)
                dl_size = _os.path.getsize(replay_path)
                print(f"[abs-modal] downloaded pre-built replay CSV {dl_size / 1024 / 1024:.1f} MB")
                return replay_path
            except Exception as _dl_exc:
                print(f"[abs-modal] pre-built replay CSV download failed: {_dl_exc} — falling back to background rebuild")
                try:
                    Path(replay_path).unlink(missing_ok=True)
                except Exception:
                    pass
        _start_background_replay_refresh(scope=resolved_scope)
        raise HTTPException(
            status_code=503,
            detail=(
                "Replay dataset is being built in the background — please retry in 2–3 minutes. "
                f"(scope={resolved_scope})"
            ),
        )

    def _require_replay_service(scope: str) -> RecommendService:
        resolved_scope = _resolve_replay_scope(scope)
        replay_path = _ensure_replay_dataset_exists(resolved_scope)
        cached_path = STATE.replay_service_paths.get(resolved_scope)
        if cached_path == replay_path and resolved_scope in STATE.replay_services:
            return STATE.replay_services[resolved_scope]
        try:
            replay_service = RecommendService(
                pitch_events_csv_path=replay_path,
                policy_config=policy_config,
                threshold_profile=settings.abs_threshold_profile,
                core_model_version=settings.abs_core_model_version,
                policy_version=settings.abs_policy_version,
                execution_model_version=settings.abs_execution_model_version,
                aptitude_model_version=settings.abs_aptitude_model_version,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Replay service init failed: {exc}") from exc

        STATE.replay_services[resolved_scope] = replay_service
        STATE.replay_service_paths[resolved_scope] = replay_path
        return replay_service

    @contextmanager
    def _open_csv_source(source: str, timeout: float = 8.0):
        if source.startswith("http://") or source.startswith("https://"):
            request = UrlRequest(
                source,
                method="GET",
                headers={"User-Agent": "the-brain-abs/1.0"},
            )
            response = urlopen(request, timeout=timeout)
            wrapped = io.TextIOWrapper(response, encoding="utf-8", newline="")
            try:
                yield wrapped
            finally:
                try:
                    wrapped.close()
                finally:
                    response.close()
            return

        with Path(source).open("r", encoding="utf-8", newline="") as handle:
            yield handle

    def _load_replay_refresh_meta(scope: str, replay_path: str) -> dict[str, Any]:
        cached = STATE.replay_refresh_meta.get(scope)
        loaded = read_replay_refresh_meta(replay_path) or {}
        # When local filesystem is empty (running in API container which doesn't share
        # disk with the job container), fall back to the Meta persisted in Modal Dict.
        if not loaded:
            try:
                dict_meta = replay_catalog_store.get(f"meta:{scope}")
                if isinstance(dict_meta, dict):
                    loaded = dict_meta
            except Exception:
                pass
        if loaded:
            if (
                not isinstance(cached, dict)
                or loaded.get("last_refresh_at") != cached.get("last_refresh_at")
                or loaded.get("status") != cached.get("status")
            ):
                _invalidate_replay_caches(scope)
            STATE.replay_refresh_meta[scope] = loaded
            return loaded
        if isinstance(cached, dict) and cached.get("output_csv") == replay_path:
            return cached
        return loaded

    def _replay_dataset_stats(scope: str, active_service: RecommendService | None = None) -> dict[str, Any]:
        cached = STATE.replay_dataset_stats_cache.get(scope)
        if cached is not None:
            return cached

        replay_path = _replay_csv_path(scope)
        refresh_meta = _load_replay_refresh_meta(scope, replay_path)
        rows = None
        if Path(replay_path).exists():
            try:
                rows = count_csv_data_rows(replay_path)
            except Exception:
                rows = None
        games = None
        if active_service is not None:
            games = len({str(event.game_id) for event in active_service.events})
        stats = {
            "scope": scope,
            "scope_tag": replay_scope_tag(scope),
            "rows": rows,
            "games": games,
            "source_min_game_date": refresh_meta.get("source_min_game_date"),
            "source_max_game_date": refresh_meta.get("source_max_game_date"),
            "last_refresh_at": refresh_meta.get("last_refresh_at"),
            "last_refresh_status": refresh_meta.get("status"),
            "output_csv": replay_path,
        }
        STATE.replay_dataset_stats_cache[scope] = stats
        return stats

    REPLAY_BEST_FOR_DEMO_BUCKET = 5

    def _replay_actual_sample_strength_flag(used_rows: int) -> str:
        if used_rows <= 0:
            return "none"
        if used_rows < 5:
            return "limited"
        return "strong"

    def _replay_actual_coverage_flag(actual_challenges: int) -> str:
        sample_strength = _replay_actual_sample_strength_flag(actual_challenges)
        if sample_strength == "none":
            return "none"
        if sample_strength == "limited":
            return "partial"
        return "good"

    def _replay_linkage_completeness_flag(
        *,
        actual_metrics_valid: bool,
        collected_rows: int,
        unmatched_rows: int,
        suppressed_rows: int,
        used_rows: int,
    ) -> str:
        if not actual_metrics_valid and (collected_rows > 0 or suppressed_rows > 0):
            return "suppressed"
        if collected_rows <= 0 or used_rows <= 0:
            return "none"
        if suppressed_rows > 0 or unmatched_rows > 0 or used_rows < collected_rows:
            return "partial"
        return "complete"

    def _replay_linkage_status(
        *,
        actual_metrics_valid: bool,
        collected_rows: int,
        unmatched_rows: int,
        suppressed_rows: int,
        used_rows: int,
    ) -> str:
        completeness = _replay_linkage_completeness_flag(
            actual_metrics_valid=actual_metrics_valid,
            collected_rows=collected_rows,
            unmatched_rows=unmatched_rows,
            suppressed_rows=suppressed_rows,
            used_rows=used_rows,
        )
        if completeness == "complete":
            return "good"
        return completeness

    def _replay_linkage_reason(
        *,
        actual_metrics_valid: bool,
        actual_metrics_reason: str | None,
        collected_rows: int,
        linked_rows: int,
        unmatched_rows: int,
        suppressed_rows: int,
        used_rows: int,
    ) -> str:
        if not actual_metrics_valid and linked_rows > 0:
            return actual_metrics_reason or "Rows were linked, but quality checks excluded them from actual-vs-policy metrics."
        if used_rows <= 0 and collected_rows > 0 and unmatched_rows > 0:
            return "Official challenge data exists upstream, but no trusted pitch-level rows were linked for this game."
        if used_rows <= 0:
            return "No official challenge rows were collected for this game."
        if suppressed_rows > 0:
            return "Rows were linked, but quality checks excluded some official rows from actual-vs-policy metrics."
        if unmatched_rows > 0:
            return "Some official challenge rows were linked for this game, but not all collected rows mapped cleanly to replay pitches."
        if used_rows < 5:
            return "All collected official rows were linked for this game, but the usable sample is still limited."
        return "All collected official rows for this game were linked and used."

    def _hydrate_game_metadata_from_statcast(scope: str, games_by_id: dict[str, dict[str, Any]]) -> None:
        sources: list[str] = []
        replay_path = _replay_csv_path(scope)
        if Path(replay_path).exists():
            sources.append(replay_path)
        replay_source = settings.abs_replay_source_uri or settings.abs_raw_statcast_uri
        if replay_source:
            sources.append(replay_source)
        for local_candidate in [
            "/root/project/data/production/statcast_merged_with_statsapi_backfill.csv",
            "/root/project/data/production/statcast_merged_backfill.csv",
            "/root/project/data/production/statcast_export.csv",
        ]:
            if Path(local_candidate).exists() and local_candidate not in sources:
                sources.append(local_candidate)
        if not sources:
            return
        unresolved = {
            gid
            for gid, meta in games_by_id.items()
            if not meta.get("date") or not meta.get("home_team") or not meta.get("away_team")
        }
        if not unresolved:
            return

        for source in sources:
            if not unresolved:
                break
            try:
                with _open_csv_source(source, timeout=20.0) as handle:
                    reader = csv.DictReader(handle)
                    headers = reader.fieldnames or []
                    game_key = "game_pk" if "game_pk" in headers else ("game_id" if "game_id" in headers else None)
                    date_key = "game_date" if "game_date" in headers else ("officialDate" if "officialDate" in headers else None)
                    home_key = "home_team" if "home_team" in headers else ("home_name" if "home_name" in headers else None)
                    away_key = "away_team" if "away_team" in headers else ("away_name" if "away_name" in headers else None)
                    if not game_key:
                        continue

                    for row in reader:
                        if not unresolved:
                            break
                        gid = str(row.get(game_key, "")).strip()
                        if not gid or gid not in unresolved:
                            continue

                        meta = games_by_id[gid]
                        if date_key and not meta.get("date"):
                            date_val = str(row.get(date_key, "")).strip()
                            if date_val:
                                meta["date"] = date_val
                        if home_key and not meta.get("home_team"):
                            home_val = str(row.get(home_key, "")).strip()
                            if home_val:
                                meta["home_team"] = home_val
                        if away_key and not meta.get("away_team"):
                            away_val = str(row.get(away_key, "")).strip()
                            if away_val:
                                meta["away_team"] = away_val

                        if meta.get("date") and meta.get("home_team") and meta.get("away_team"):
                            unresolved.discard(gid)
            except Exception as exc:
                print(f"[abs-modal] replay metadata enrichment failed from {source}: {exc}")

    def _build_games_catalog_base_from_csv(scope: str) -> list[dict[str, Any]]:
        cached = STATE.replay_games_cache.get(scope)
        if cached is not None:
            return cached

        # If the CSV doesn't exist locally, check Modal Dict for a pre-built catalog
        # (written by replay_refresh_job after each successful build).
        resolved_scope_check = _resolve_replay_scope(scope)
        if not Path(_replay_csv_path(resolved_scope_check)).exists():
            try:
                stored = replay_catalog_store.get(f"catalog:{resolved_scope_check}")
                if stored and isinstance(stored, list) and len(stored) > 0:
                    catalog = [dict(g) for g in stored if isinstance(g, dict)]
                    STATE.replay_games_cache[resolved_scope_check] = catalog
                    print(f"[abs-modal] games catalog loaded from Modal Dict scope={resolved_scope_check} games={len(catalog)}")
                    return catalog
            except Exception as _dict_exc:
                print(f"[abs-modal] Modal Dict catalog lookup failed for scope={resolved_scope_check}: {_dict_exc}")

        replay_path = _ensure_replay_dataset_exists(scope)

        games_by_id: dict[str, dict[str, Any]] = {}
        with Path(replay_path).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                gid = str(row.get("game_id", "")).strip()
                if not gid:
                    continue
                meta = games_by_id.get(gid)
                if meta is None:
                    meta = {
                        "game_id": gid,
                        "date": str(row.get("game_date", "")).strip() or None,
                        "home_team": str(row.get("home_team", "")).strip() or None,
                        "away_team": str(row.get("away_team", "")).strip() or None,
                        "pitch_count": 0,
                        "actual_challenges_in_source": 0,
                        "actual_correct_challenges_in_source": 0,
                    }
                    games_by_id[gid] = meta
                meta["pitch_count"] = int(meta["pitch_count"]) + 1
                meta["actual_challenges_in_source"] = int(meta["actual_challenges_in_source"]) + _to_int(
                    row.get("challenged"), 0
                )
                meta["actual_correct_challenges_in_source"] = int(meta["actual_correct_challenges_in_source"]) + _to_int(
                    row.get("challenge_correct"), 0
                )

        _hydrate_game_metadata_from_statcast(scope, games_by_id)

        dataset_stats = _replay_dataset_stats(scope)
        dataset_stats["games"] = len(games_by_id)
        STATE.replay_dataset_stats_cache[scope] = dataset_stats

        games = list(games_by_id.values())
        for game in games:
            game["date"] = game.get("date") or "Unknown"
            game["home_team"] = game.get("home_team") or "TBD"
            game["away_team"] = game.get("away_team") or "TBD"
            game["has_actual_challenges"] = int(game.get("actual_challenges_in_source") or 0) > 0
            game["scope_tag"] = replay_scope_tag(scope)
            game["last_data_refresh_at"] = dataset_stats.get("last_refresh_at")
            game["source_max_game_date"] = dataset_stats.get("source_max_game_date")

        games.sort(
            key=lambda game: (
                str(game.get("date", "")),
                _safe_int_token(str(game.get("game_id", ""))),
            ),
            reverse=True,
        )
        STATE.replay_games_cache[scope] = games
        return games

    def _build_games_catalog_base(scope: str, active_service: RecommendService) -> list[dict[str, Any]]:
        cached = STATE.replay_games_cache.get(scope)
        if cached is not None:
            return cached

        try:
            return _build_games_catalog_base_from_csv(scope)
        except Exception as exc:
            print(f"[abs-modal] replay catalog CSV path failed for scope={scope}: {exc}")

        dataset_stats = _replay_dataset_stats(scope, active_service)
        games_by_id: dict[str, dict[str, Any]] = {}
        for event in active_service.events:
            gid = str(event.game_id)
            meta = games_by_id.get(gid)
            if meta is None:
                meta = {
                    "game_id": gid,
                    "date": None,
                    "home_team": None,
                    "away_team": None,
                    "pitch_count": 0,
                    "actual_challenges_in_source": 0,
                    "actual_correct_challenges_in_source": 0,
                }
                games_by_id[gid] = meta
            meta["pitch_count"] = int(meta["pitch_count"]) + 1
            meta["actual_challenges_in_source"] = int(meta["actual_challenges_in_source"]) + int(
                getattr(event, "challenged", 0) or 0
            )
            meta["actual_correct_challenges_in_source"] = int(meta["actual_correct_challenges_in_source"]) + int(
                getattr(event, "challenge_correct", 0) or 0
            )

        _hydrate_game_metadata_from_statcast(scope, games_by_id)

        games = list(games_by_id.values())
        for game in games:
            game["date"] = game.get("date") or "Unknown"
            game["home_team"] = game.get("home_team") or "TBD"
            game["away_team"] = game.get("away_team") or "TBD"
            game["has_actual_challenges"] = int(game.get("actual_challenges_in_source") or 0) > 0
            game["scope_tag"] = replay_scope_tag(scope)
            game["last_data_refresh_at"] = dataset_stats.get("last_refresh_at")
            game["source_max_game_date"] = dataset_stats.get("source_max_game_date")

        games.sort(
            key=lambda game: (
                str(game.get("date", "")),
                _safe_int_token(str(game.get("game_id", ""))),
            ),
            reverse=True,
        )
        STATE.replay_games_cache[scope] = games
        return games

    def _compute_game_stats_for_catalog(
        scope: str,
        active_service: RecommendService,
        game_id: str,
        game_meta: dict[str, Any],
        game_events: list[Any],
        refresh_meta: dict[str, Any],
        official_counts_by_game: dict[str, int],
        latest_ingestion_details: dict[str, Any],
        policy_team: str | None = None,
    ) -> dict[str, Any]:
        challenges_left = 2
        cumulative_run_value = 0.0
        cumulative_expected_policy_ev = 0.0
        challenges_recommended = 0
        successful_challenges = 0
        failed_challenges = 0
        positive_ev_holds = 0
        missed_overturns_hindsight = 0
        actual_correct_challenges_in_source = 0
        actual_challenges_in_source = 0
        official_actual_challenges_in_source = 0
        policy_actual_disagreements = 0
        policy_would_challenge_vs_actual_hold = 0
        actual_challenged_vs_policy_hold = 0
        counterfactual_delta_vs_actual = 0.0
        home_team = str(game_meta.get("home_team") or getattr(game_events[0], "home_team", "TBD") or "TBD")
        away_team = str(game_meta.get("away_team") or getattr(game_events[0], "away_team", "TBD") or "TBD")
        actual_inventory_by_team = {
            home_team: 2,
            away_team: 2,
        }

        for event in game_events:
            sz_top, sz_bot = _event_zone_bounds(event)
            context = ChallengeContext(
                game_id=str(event.game_id),
                inning=int(event.inning),
                half=str(event.half),
                outs=int(event.outs),
                base_state=str(event.base_state),
                score_diff=int(event.score_diff),
                count=str(event.count),
                challenges_left=challenges_left,
                is_final_challenge=challenges_left == 1,
                batter_id=str(event.batter_id),
                pitcher_id=str(event.pitcher_id),
                catcher_id=str(event.catcher_id),
            )
            observation = PitchObservation(
                pitch_id=str(event.pitch_id),
                px=float(event.px),
                pz=float(event.pz),
                plate_x=float(event.plate_x),
                plate_z=float(event.plate_z),
                velo=float(event.velo),
                spin=float(event.spin),
                movement=float(event.movement),
                handedness_matchup=str(event.handedness_matchup),
                call_on_field=str(event.call_on_field),
                sz_top=sz_top,
                sz_bot=sz_bot,
            )
            request = RecommendationRequest(
                challenge_context=context,
                pitch_observation=observation,
                model_version=settings.abs_policy_version,
            )

            p_overturn = active_service.overturn_model.predict_proba_request(context, observation)
            uncertainty = active_service.overturn_model.estimate_uncertainty(p_overturn)
            run_swing = active_service.run_swing_model.predict_from_context(context)
            policy_response = active_service.policy_engine.recommend(
                request=request,
                overturn_probability=p_overturn,
                expected_run_swing=run_swing,
                uncertainty=uncertainty,
            )

            overturn_flag = bool(event.call_on_field != event.abs_truth_call)
            recommendation = policy_response.recommendation.value
            realized_ev = 0.0
            batting_team = away_team if str(event.half) == "top" else home_team
            fielding_team = home_team if str(event.half) == "top" else away_team
            eligible_team = _eligible_team_for_pitch(str(event.call_on_field), str(event.half), home_team, away_team)
            # When filtering by policy_team, skip pitches where the team is not eligible to challenge
            if policy_team is not None and policy_team != eligible_team:
                continue
            raw_actual_challenged = _coerce_boolish(getattr(event, "challenged", 0))
            raw_actual_team = _normalize_replay_team(getattr(event, "challenge_team", ""), home_team, away_team)
            if raw_actual_challenged and raw_actual_team is None:
                raw_actual_team = eligible_team
            actual_challenged = raw_actual_challenged and (policy_team is None or raw_actual_team == policy_team)
            actual_challenge_correct = _coerce_boolish(getattr(event, "challenge_correct", 0)) if actual_challenged else False
            outcome_source_type = str(getattr(event, "outcome_source_type", "inferred") or "inferred").strip().lower()
            actual_recommendation = "CHALLENGE" if actual_challenged else "HOLD"
            policy_counterfactual_realized_ev = 0.0
            actual_realized_ev = 0.0

            if recommendation == "CHALLENGE" and challenges_left > 0:
                challenges_recommended += 1
                cumulative_expected_policy_ev += float(policy_response.net_ev)
                if overturn_flag:
                    successful_challenges += 1
                    realized_ev = float(event.run_expectancy_delta)
                else:
                    failed_challenges += 1
                    challenges_left = max(0, challenges_left - 1)
                    realized_ev = float(-policy_response.future_option_cost)
                cumulative_run_value += realized_ev
            elif challenges_left > 0:
                if float(policy_response.net_ev) > 0:
                    positive_ev_holds += 1
                if overturn_flag:
                    missed_overturns_hindsight += 1

            if recommendation == "CHALLENGE":
                policy_counterfactual_realized_ev = (
                    float(event.run_expectancy_delta) if overturn_flag else float(-policy_response.future_option_cost)
                )

            if actual_challenged:
                actual_challenges_in_source += 1
                if outcome_source_type == "official":
                    official_actual_challenges_in_source += 1
                if actual_challenge_correct:
                    actual_correct_challenges_in_source += 1
                    actual_realized_ev = float(event.run_expectancy_delta)
                else:
                    actual_realized_ev = float(-policy_response.future_option_cost)
                    actual_team = str(getattr(event, "challenge_team", "") or "")
                    if actual_team in actual_inventory_by_team:
                        actual_inventory_by_team[actual_team] = max(0, actual_inventory_by_team[actual_team] - 1)

            policy_disagrees_with_actual = recommendation != actual_recommendation
            if policy_disagrees_with_actual:
                policy_actual_disagreements += 1
                counterfactual_run_value_delta = policy_counterfactual_realized_ev - actual_realized_ev
                counterfactual_delta_vs_actual += counterfactual_run_value_delta
                if recommendation == "CHALLENGE":
                    policy_would_challenge_vs_actual_hold += 1
                else:
                    actual_challenged_vs_policy_hold += 1

        official_detail_rows_by_game = refresh_meta.get("official_detail_rows_by_game")
        if not isinstance(official_detail_rows_by_game, dict):
            official_detail_rows_by_game = {}
        official_rows_collected_for_game = _to_int(
            official_detail_rows_by_game.get(game_id),
            official_counts_by_game.get(game_id, 0),
        )
        actual_metrics_valid = True
        actual_metrics_reason: str | None = None
        pitch_count = max(1, len(game_events))
        official_challenge_density = official_actual_challenges_in_source / pitch_count
        savant_benchmark = latest_ingestion_details.get("savant_abs_benchmark")
        if not isinstance(savant_benchmark, dict):
            savant_benchmark = {}
        savant_benchmark_comparison = latest_ingestion_details.get("savant_abs_benchmark_comparison")
        if not isinstance(savant_benchmark_comparison, dict):
            savant_benchmark_comparison = {}
        if official_actual_challenges_in_source > MAX_ACTUAL_CHALLENGES_PER_GAME:
            actual_metrics_valid = False
            actual_metrics_reason = (
                "Suppressed: official challenge count exceeds per-game cap "
                f"({official_actual_challenges_in_source} > {MAX_ACTUAL_CHALLENGES_PER_GAME})."
            )
        elif official_challenge_density > MAX_ACTUAL_CHALLENGE_DENSITY:
            actual_metrics_valid = False
            actual_metrics_reason = (
                "Suppressed: official challenge density exceeds threshold "
                f"({official_challenge_density:.1%} > {MAX_ACTUAL_CHALLENGE_DENSITY:.0%})."
            )
        elif actual_challenges_in_source > 0 and official_actual_challenges_in_source == 0:
            actual_metrics_valid = False
            actual_metrics_reason = "Suppressed: challenge rows exist without official lineage."
        elif savant_benchmark_comparison.get("status") == "mismatch":
            benchmark_total = savant_benchmark_comparison.get("benchmark_total_challenges")
            benchmark_rate = savant_benchmark_comparison.get("benchmark_overturn_rate")
            official_rate = savant_benchmark_comparison.get("official_overturn_rate")
            actual_metrics_reason = (
                "Official challenge coverage is partial versus the Baseball Savant ABS benchmark "
                f"({benchmark_total} benchmark challenges; internal overturn rate "
                f"{official_rate:.1%} vs {benchmark_rate:.1%})."
                if isinstance(benchmark_total, int)
                and isinstance(benchmark_rate, (int, float))
                and isinstance(official_rate, (int, float))
                else "Official challenge coverage is partial versus the Baseball Savant ABS benchmark."
            )

        official_rows_linked_to_replay = official_actual_challenges_in_source
        official_rows_collected_for_game = max(official_rows_collected_for_game, official_rows_linked_to_replay)
        official_rows_used_for_actual_metrics = official_rows_linked_to_replay if actual_metrics_valid else 0
        official_rows_suppressed = (
            official_rows_linked_to_replay if not actual_metrics_valid and official_rows_linked_to_replay > 0 else 0
        )
        official_rows_unmatched = max(0, official_rows_collected_for_game - official_rows_linked_to_replay)
        linkage_completeness_flag = _replay_linkage_completeness_flag(
            actual_metrics_valid=actual_metrics_valid,
            collected_rows=official_rows_collected_for_game,
            unmatched_rows=official_rows_unmatched,
            suppressed_rows=official_rows_suppressed,
            used_rows=official_rows_used_for_actual_metrics,
        )
        actual_sample_strength_flag = _replay_actual_sample_strength_flag(official_rows_used_for_actual_metrics)
        usable_actual_rows = official_rows_used_for_actual_metrics
        linkage_rate = 0.0
        if official_rows_collected_for_game > 0:
            linkage_rate = usable_actual_rows / official_rows_collected_for_game
        has_policy_challenge = challenges_recommended > 0
        has_successful_policy_challenge = successful_challenges > 0
        nonzero_counterfactual = abs(counterfactual_delta_vs_actual) > 1e-9
        nonzero_realized_run_value = abs(cumulative_run_value) > 1e-9
        demo_score = 0.0
        if actual_metrics_valid and actual_sample_strength_flag != "none":
            demo_score += 1_000_000
        if linkage_completeness_flag == "complete":
            demo_score += 50_000
        elif linkage_completeness_flag == "partial":
            demo_score += 20_000
        demo_score += usable_actual_rows * 10_000
        demo_score += linkage_rate * 1_000
        if has_policy_challenge:
            demo_score += 100
        if has_successful_policy_challenge:
            demo_score += 25
        if nonzero_counterfactual:
            demo_score += 10
        if nonzero_realized_run_value:
            demo_score += 5
        return {
            "expected_policy_edge": round(float(cumulative_expected_policy_ev), 6),
            "realized_run_value": round(float(cumulative_run_value), 6),
            "policy_challenges_recommended": challenges_recommended,
            "successful_challenges": successful_challenges,
            "failed_challenges": failed_challenges,
            "actual_challenges_in_source": official_actual_challenges_in_source if actual_metrics_valid else 0,
            "actual_correct_challenges_in_source": actual_correct_challenges_in_source if actual_metrics_valid else 0,
            "policy_actual_disagreements": policy_actual_disagreements if actual_metrics_valid else 0,
            "policy_would_challenge_vs_actual_hold": (
                policy_would_challenge_vs_actual_hold if actual_metrics_valid else 0
            ),
            "actual_challenged_vs_policy_hold": actual_challenged_vs_policy_hold if actual_metrics_valid else 0,
            "counterfactual_delta_vs_actual": round(float(counterfactual_delta_vs_actual), 6) if actual_metrics_valid else 0.0,
            "positive_ev_holds": positive_ev_holds,
            "missed_positive_ev_opportunities": positive_ev_holds,
            "missed_overturn_opportunities": missed_overturns_hindsight,
            "has_actual_challenges": official_actual_challenges_in_source > 0 if actual_metrics_valid else False,
            "generated_at": _utc_now_iso(),
            "actual_challenges_used": official_actual_challenges_in_source if actual_metrics_valid else 0,
            "actual_challenges_correct": actual_correct_challenges_in_source if actual_metrics_valid else 0,
            "expected_edge": round(float(cumulative_expected_policy_ev), 6),
            "scope_tag": replay_scope_tag(scope),
            "last_data_refresh_at": game_meta.get("last_data_refresh_at"),
            "source_max_game_date": game_meta.get("source_max_game_date"),
            "actual_coverage_flag": (
                _replay_actual_coverage_flag(official_rows_used_for_actual_metrics) if actual_metrics_valid else "none"
            ),
            "actual_metrics_valid": actual_metrics_valid,
            "actual_metrics_reason": actual_metrics_reason,
            "linkage_completeness_flag": linkage_completeness_flag,
            "actual_sample_strength_flag": actual_sample_strength_flag,
            "official_rows_collected_for_game": official_rows_collected_for_game,
            "official_rows_linked_to_replay": official_rows_linked_to_replay,
            "official_rows_unmatched": official_rows_unmatched,
            "official_rows_suppressed": official_rows_suppressed,
            "official_rows_used_for_actual_metrics": official_rows_used_for_actual_metrics,
            "demo_score": round(demo_score, 6),
            "demo_status": (
                "suppressed_actual_comparison"
                if not actual_metrics_valid and usable_actual_rows > 0
                else "usable_actual_comparison"
                if actual_metrics_valid and actual_sample_strength_flag != "none"
                else "policy_only_example"
            ),
        }

    def _build_ranked_games_catalog(scope: str, active_service: RecommendService) -> list[dict[str, Any]]:
        cached = STATE.replay_catalog_cache.get(scope)
        if cached is not None:
            return cached
        base_catalog = _build_games_catalog_base(scope, active_service)
        refresh_meta = _load_replay_refresh_meta(scope, _replay_csv_path(scope))
        official_counts_by_game = _load_official_challenge_counts_by_game()
        latest_ingestion = _get_latest_ingestion_row_with_timeout(timeout_seconds=2.0)
        latest_ingestion_details = latest_ingestion.get("details") if isinstance(latest_ingestion, dict) else None
        if not isinstance(latest_ingestion_details, dict):
            latest_ingestion_details = {}
        events_by_game: dict[str, list[Any]] = {}
        for event in active_service.events:
            events_by_game.setdefault(str(event.game_id), []).append(event)
        for game_events in events_by_game.values():
            game_events.sort(key=_pitch_sort_key)

        catalog: list[dict[str, Any]] = []
        scope_stats_cache = STATE.replay_game_stats_cache.setdefault(scope, {})
        for game in base_catalog:
            game_id = str(game.get("game_id", "")).strip()
            if not game_id:
                continue
            stats = scope_stats_cache.get(game_id)
            if stats is None:
                game_events = events_by_game.get(game_id)
                if not game_events:
                    continue
                stats = _compute_game_stats_for_catalog(
                    scope,
                    active_service,
                    game_id,
                    game,
                    game_events,
                    refresh_meta,
                    official_counts_by_game,
                    latest_ingestion_details,
                )
                scope_stats_cache[game_id] = stats
            enriched = dict(game)
            enriched.update(stats)
            catalog.append(enriched)

        STATE.replay_catalog_cache[scope] = catalog
        return catalog

    def _load_ranked_games_catalog(scope: str) -> list[dict[str, Any]]:
        cached = STATE.replay_catalog_cache.get(scope)
        if cached is not None:
            return [dict(game) for game in cached]
        # Try Modal Dict first (survives container restarts, written during refresh)
        try:
            stored = replay_catalog_store.get(f"catalog:{scope}")
            if stored and isinstance(stored, list):
                catalog = [dict(game) for game in stored if isinstance(game, dict)]
                STATE.replay_catalog_cache[scope] = catalog
                return [dict(game) for game in catalog]
        except KeyError:
            pass
        except Exception as exc:
            print(f"[abs-modal] failed to load ranked catalog from Modal Dict for scope={scope}: {exc}")
        # Fall back to filesystem (only available if written in same container session)
        replay_path = _replay_csv_path(scope)
        payload = read_replay_catalog(replay_path)
        if not payload:
            return []
        catalog = [dict(game) for game in payload if isinstance(game, dict)]
        STATE.replay_catalog_cache[scope] = catalog
        return [dict(game) for game in catalog]

    def _build_games_catalog(
        scope: str,
        active_service: RecommendService | None = None,
        rank_by: str = "recent",
    ) -> list[dict[str, Any]]:
        if rank_by == "recent":
            if active_service is None:
                raise HTTPException(status_code=503, detail="Replay service unavailable for recent catalog build.")
            return [dict(game) for game in _build_games_catalog_base(scope, active_service)]

        catalog = _load_ranked_games_catalog(scope)
        if not catalog:
            raise HTTPException(
                status_code=503,
                detail="Ranked replay catalog unavailable; falling back to recent games.",
            )
        if rank_by == "expected_edge":
            catalog.sort(
                key=lambda game: (
                    float(game.get("expected_policy_edge", 0.0)),
                    str(game.get("date", "")),
                    _safe_int_token(str(game.get("game_id", ""))),
                ),
                reverse=True,
            )
            return catalog

        catalog.sort(
            key=lambda game: (
                float(game.get("demo_score", 0.0)),
                str(game.get("date", "")),
                _safe_int_token(str(game.get("game_id", ""))),
            ),
            reverse=True,
        )
        remaining_best_for_demo = REPLAY_BEST_FOR_DEMO_BUCKET
        for game in catalog:
            status = str(game.get("demo_status") or "policy_only_example")
            if status != "usable_actual_comparison":
                continue
            if remaining_best_for_demo > 0:
                game["demo_status"] = "best_for_demo"
                remaining_best_for_demo -= 1
        return catalog

    def _build_and_persist_ranked_catalog(scope: str, active_service: RecommendService) -> list[dict[str, Any]]:
        catalog = _build_ranked_games_catalog(scope, active_service)
        replay_path = _replay_csv_path(scope)
        write_replay_catalog(replay_path, catalog)
        # Also store in Modal Dict so it survives container restarts
        try:
            replay_catalog_store.put(f"catalog:{scope}", catalog)
        except Exception as exc:
            print(f"[abs-modal] failed to persist ranked catalog to Modal Dict for scope={scope}: {exc}")
        STATE.replay_catalog_cache[scope] = [dict(g) for g in catalog]
        return catalog

    def _prewarm_replay_payloads(
        scope: str,
        active_service: RecommendService,
        *,
        limit: int = REPLAY_PREWARM_GAME_LIMIT,
    ) -> dict[str, int]:
        catalog = _build_games_catalog_base(scope, active_service)
        selected_game_ids = [
            str(game.get("game_id", "")).strip()
            for game in catalog[: max(0, limit)]
            if str(game.get("game_id", "")).strip()
        ]
        warmed = 0
        failed = 0
        for game_id in selected_game_ids:
            try:
                _build_replay_payload(scope, active_service, game_id)
                warmed += 1
            except Exception as exc:
                failed += 1
                print(f"[abs-modal] replay payload prewarm failed for scope={scope} game_id={game_id}: {exc}")
        return {
            "requested": len(selected_game_ids),
            "warmed": warmed,
            "failed": failed,
        }

    def _build_replay_payload(
        scope: str,
        active_service: RecommendService,
        game_id: str,
        policy_team_override: str | None = None,
    ) -> dict[str, Any]:
        scope_cache = STATE.replay_payload_cache.setdefault(scope, {})
        game_events = [event for event in active_service.events if str(event.game_id) == game_id]
        if not game_events:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found in replay source")
        game_events.sort(key=_pitch_sort_key)

        games_catalog = _build_games_catalog_base(scope, active_service)
        game_meta = next((game for game in games_catalog if game["game_id"] == game_id), None)
        if game_meta is None:
            game_meta = {
                "game_id": game_id,
                "date": "Unknown",
                "home_team": "TBD",
                "away_team": "TBD",
                "pitch_count": len(game_events),
                "scope_tag": replay_scope_tag(scope),
                "last_data_refresh_at": None,
                "source_max_game_date": None,
            }

        refresh_meta = _load_replay_refresh_meta(scope, _replay_csv_path(scope))
        official_detail_rows_by_game = refresh_meta.get("official_detail_rows_by_game")
        if not isinstance(official_detail_rows_by_game, dict):
            official_detail_rows_by_game = {}
        official_rows_collected_for_game = _to_int(
            official_detail_rows_by_game.get(game_id),
            _load_official_challenge_counts_by_game().get(game_id, 0),
        )

        home_team = str(game_meta.get("home_team") or getattr(game_events[0], "home_team", "TBD") or "TBD")
        away_team = str(game_meta.get("away_team") or getattr(game_events[0], "away_team", "TBD") or "TBD")
        resolved_policy_team = _resolve_replay_policy_team(policy_team_override, home_team, away_team)
        cache_key = game_id if resolved_policy_team is None else f"{game_id}::{resolved_policy_team}"
        cached = scope_cache.get(cache_key)
        if cached is not None:
            return cached

        challenges_left = 2
        cumulative_run_value = 0.0
        cumulative_expected_policy_ev = 0.0
        challenges_recommended = 0
        successful_challenges = 0
        failed_challenges = 0
        positive_ev_holds = 0
        missed_overturns_hindsight = 0
        actual_challenges_in_source = 0
        actual_correct_challenges_in_source = 0
        official_actual_challenges_in_source = 0
        inferred_rows_present = False
        policy_actual_disagreements = 0
        policy_would_challenge_vs_actual_hold = 0
        actual_challenged_vs_policy_hold = 0
        counterfactual_delta_vs_actual = 0.0
        pitches: list[dict[str, Any]] = []
        actual_inventory_by_team = {
            home_team: 2,
            away_team: 2,
        }

        for index, event in enumerate(game_events):
            sz_top, sz_bot = _event_zone_bounds(event)
            batting_team, fielding_team = _teams_for_half(str(event.half), home_team, away_team)
            eligible_team = _eligible_team_for_pitch(str(event.call_on_field), str(event.half), home_team, away_team)
            policy_team = resolved_policy_team or eligible_team
            policy_score_diff = _score_diff_for_selected_team(int(event.score_diff), policy_team, batting_team, fielding_team)
            policy_team_challenges_left = challenges_left if resolved_policy_team else actual_inventory_by_team.get(policy_team, 2)
            opponent_team = away_team if policy_team == home_team else home_team
            opponent_challenges_left = actual_inventory_by_team.get(opponent_team, 2)
            context = ChallengeContext(
                game_id=str(event.game_id),
                inning=int(event.inning),
                half=str(event.half),
                outs=int(event.outs),
                base_state=str(event.base_state),
                score_diff=policy_score_diff,
                count=str(event.count),
                challenges_left=policy_team_challenges_left,
                is_final_challenge=policy_team_challenges_left == 1,
                batter_id=str(event.batter_id),
                pitcher_id=str(event.pitcher_id),
                catcher_id=str(event.catcher_id),
            )
            observation = PitchObservation(
                pitch_id=str(event.pitch_id),
                px=float(event.px),
                pz=float(event.pz),
                plate_x=float(event.plate_x),
                plate_z=float(event.plate_z),
                velo=float(event.velo),
                spin=float(event.spin),
                movement=float(event.movement),
                handedness_matchup=str(event.handedness_matchup),
                call_on_field=str(event.call_on_field),
                sz_top=sz_top,
                sz_bot=sz_bot,
            )
            request = RecommendationRequest(
                challenge_context=context,
                pitch_observation=observation,
                model_version=settings.abs_policy_version,
            )

            p_overturn = active_service.overturn_model.predict_proba_request(context, observation)
            uncertainty = active_service.overturn_model.estimate_uncertainty(p_overturn)
            run_swing = active_service.run_swing_model.predict_from_context(context)
            policy_response = active_service.policy_engine.recommend(
                request=request,
                overturn_probability=p_overturn,
                expected_run_swing=run_swing,
                uncertainty=uncertainty,
            )
            if resolved_policy_team is not None and policy_team != eligible_team:
                policy_response = _policy_team_not_eligible_response(policy_response)
            dugout_signal, _, _ = active_service.dugout_signal(
                context=context,
                recommendation=policy_response.recommendation.value,
                confidence=policy_response.confidence,
                net_ev=policy_response.net_ev,
            )

            overturn_flag = bool(event.call_on_field != event.abs_truth_call)
            recommendation = policy_response.recommendation.value
            realized_ev: float | None = None
            challenged = False
            raw_actual_challenged = _coerce_boolish(getattr(event, "challenged", 0))
            raw_actual_challenge_correct = _coerce_boolish(getattr(event, "challenge_correct", 0))
            raw_actual_team = _normalize_replay_team(getattr(event, "challenge_team", ""), home_team, away_team)
            if raw_actual_challenged and raw_actual_team is None:
                raw_actual_team = eligible_team
            actual_team_for_view = raw_actual_team if resolved_policy_team is None else resolved_policy_team
            actual_challenged = raw_actual_challenged and (
                resolved_policy_team is None or raw_actual_team == resolved_policy_team
            )
            actual_challenge_correct = raw_actual_challenge_correct if actual_challenged else False
            outcome_source_type = str(getattr(event, "outcome_source_type", "inferred") or "inferred").strip().lower()
            if outcome_source_type != "official":
                inferred_rows_present = True
            actual_recommendation = "CHALLENGE" if actual_challenged else "HOLD"
            policy_counterfactual_realized_ev = 0.0
            actual_realized_ev = 0.0
            counterfactual_result = "same_as_actual"
            counterfactual_run_value_delta = 0.0

            if recommendation == "CHALLENGE" and policy_team_challenges_left > 0:
                challenged = True
                challenges_recommended += 1
                cumulative_expected_policy_ev += float(policy_response.net_ev)
                if overturn_flag:
                    successful_challenges += 1
                    realized_ev = float(event.run_expectancy_delta)
                else:
                    failed_challenges += 1
                    challenges_left = max(0, challenges_left - 1)
                    realized_ev = float(-policy_response.future_option_cost)
                cumulative_run_value += realized_ev
            elif policy_team_challenges_left > 0:
                if float(policy_response.net_ev) > 0:
                    positive_ev_holds += 1
                if overturn_flag:
                    missed_overturns_hindsight += 1

            if recommendation == "CHALLENGE":
                policy_counterfactual_realized_ev = (
                    float(event.run_expectancy_delta) if overturn_flag else float(-policy_response.future_option_cost)
                )

            if actual_challenged:
                actual_challenges_in_source += 1
                if outcome_source_type == "official":
                    official_actual_challenges_in_source += 1
                if actual_challenge_correct:
                    actual_correct_challenges_in_source += 1
                    actual_realized_ev = float(event.run_expectancy_delta)
                else:
                    actual_realized_ev = float(-policy_response.future_option_cost)
                    if raw_actual_team in actual_inventory_by_team:
                        actual_inventory_by_team[raw_actual_team] = max(0, actual_inventory_by_team[raw_actual_team] - 1)

            policy_disagrees_with_actual = recommendation != actual_recommendation
            disagreement_statement = "Policy and on-field agree"
            if policy_disagrees_with_actual:
                policy_actual_disagreements += 1
                counterfactual_run_value_delta = policy_counterfactual_realized_ev - actual_realized_ev
                counterfactual_delta_vs_actual += counterfactual_run_value_delta
                if recommendation == "CHALLENGE":
                    policy_would_challenge_vs_actual_hold += 1
                    disagreement_statement = "Policy would challenge; on-field held"
                    counterfactual_result = "would_overturn" if overturn_flag else "would_fail"
                else:
                    actual_challenged_vs_policy_hold += 1
                    disagreement_statement = "On-field challenged; policy would hold"
                    counterfactual_result = "would_hold"

            p_strike = 1.0 if abs(float(event.plate_x)) <= 0.83 and sz_bot <= float(event.plate_z) <= sz_top else 0.0
            leverage = float(_replay_leverage_score(event))
            leverage_adj = float(
                policy_response.net_ev
                - policy_response.expected_runs_gained
                + policy_response.future_option_cost
            )
            pitches.append(
                {
                    "index": index,
                    "pitch_id": str(event.pitch_id),
                    "game_id": str(event.game_id),
                    "inning": int(event.inning),
                    "half": str(event.half),
                    "outs": int(event.outs),
                    "count": str(event.count),
                    "base_state": str(event.base_state),
                    "score_diff": int(event.score_diff),
                    "policy_team": policy_team,
                    "batting_team": batting_team,
                    "fielding_team": fielding_team,
                    "policy_team_challenges_left": policy_team_challenges_left,
                    "opponent_challenges_left": opponent_challenges_left,
                    "policy_score_diff": policy_score_diff,
                    "score_state_text": _describe_score_state(policy_score_diff),
                    "plate_x": float(event.plate_x),
                    "plate_z": float(event.plate_z),
                    "sz_top": round(sz_top, 3),
                    "sz_bot": round(sz_bot, 3),
                    "zone_distance_to_edge": round(
                        _replay_zone_distance_to_edge(float(event.plate_x), float(event.plate_z), sz_bot, sz_top),
                        3,
                    ),
                    "call_on_field": str(event.call_on_field),
                    "abs_truth_call": str(event.abs_truth_call),
                    "overturn_flag": overturn_flag,
                    "challenged": challenged,
                    "actual_challenged": actual_challenged,
                    "actual_challenge_correct": actual_challenge_correct,
                    "actual_challenge_team": actual_team_for_view or "",
                    "outcome_source_type": outcome_source_type,
                    "outcome_source_system": str(getattr(event, "outcome_source_system", "")),
                    "outcome_confidence": str(getattr(event, "outcome_confidence", "")),
                    "actual_recommendation": actual_recommendation,
                    "policy_disagrees_with_actual": policy_disagrees_with_actual,
                    "policy_vs_on_field_text": disagreement_statement,
                    "counterfactual_result": counterfactual_result,
                    "counterfactual_result_text": {
                        "would_overturn": "Would overturn",
                        "would_fail": "Would fail",
                        "would_hold": "Would hold",
                    }.get(counterfactual_result, "Matches on-field action"),
                    "reason_codes": list(policy_response.reason_codes),
                    "top_drivers": _top_drivers_from_reason_codes(
                        list(policy_response.reason_codes),
                        float(p_overturn),
                        str(event.base_state),
                        int(policy_score_diff),
                    ),
                    "p_overturn": round(float(p_overturn), 6),
                    "run_swing": round(float(run_swing), 6),
                    "net_ev": round(float(policy_response.net_ev), 6),
                    "immediate_ev": round(float(policy_response.expected_runs_gained), 6),
                    "leverage_adjustment": round(leverage_adj, 6),
                    "opportunity_cost": round(float(policy_response.future_option_cost), 6),
                    "challenges_left": int(context.challenges_left),
                    "is_final_challenge": bool(context.is_final_challenge),
                    "retain_on_success": True,
                    "leverage_score": round(leverage, 3),
                    "leverage_bucket": _replay_leverage_bucket(leverage),
                    "recommendation": recommendation,
                    "signal_color": _signal_to_color(dugout_signal),
                    "confidence": round(float(policy_response.confidence), 6),
                    "cumulative_run_value": round(float(cumulative_run_value), 6),
                    "cumulative_expected_policy_ev": round(float(cumulative_expected_policy_ev), 6),
                    "cumulative_challenges_recommended": challenges_recommended,
                    "cumulative_correct_challenges": successful_challenges,
                    "cumulative_positive_ev_holds": positive_ev_holds,
                    "cumulative_missed_opportunities": positive_ev_holds,
                    "cumulative_missed_overturn_opportunities": missed_overturns_hindsight,
                    "cumulative_actual_challenges": actual_challenges_in_source,
                    "cumulative_actual_correct_challenges": actual_correct_challenges_in_source,
                    "cumulative_policy_actual_disagreements": policy_actual_disagreements,
                    "cumulative_counterfactual_delta_vs_actual": round(float(counterfactual_delta_vs_actual), 6),
                    "p_strike": p_strike,
                    "realized_ev": round(float(realized_ev), 6) if realized_ev is not None else None,
                    "actual_realized_ev": round(float(actual_realized_ev), 6),
                    "policy_counterfactual_realized_ev": round(float(policy_counterfactual_realized_ev), 6),
                    "counterfactual_run_value_delta": round(float(counterfactual_run_value_delta), 6),
                    "recommended_challenger": str(event.catcher_id) if recommendation == "CHALLENGE" else None,
                    "execution_probability": round(float(policy_response.confidence), 6)
                    if recommendation == "CHALLENGE"
                    else None,
                }
            )

        actual_metrics_valid = True
        actual_metrics_reason: str | None = None
        pitch_count = max(1, len(game_events))
        official_challenge_density = official_actual_challenges_in_source / pitch_count
        latest_ingestion = _get_latest_ingestion_row_with_timeout(timeout_seconds=2.0)
        latest_details = latest_ingestion.get("details") if isinstance(latest_ingestion, dict) else None
        if not isinstance(latest_details, dict):
            latest_details = {}
        savant_benchmark = latest_details.get("savant_abs_benchmark")
        if not isinstance(savant_benchmark, dict):
            savant_benchmark = {}
        savant_benchmark_comparison = latest_details.get("savant_abs_benchmark_comparison")
        if not isinstance(savant_benchmark_comparison, dict):
            savant_benchmark_comparison = {}
        if official_actual_challenges_in_source > MAX_ACTUAL_CHALLENGES_PER_GAME:
            actual_metrics_valid = False
            actual_metrics_reason = (
                "Suppressed: official challenge count exceeds per-game cap "
                f"({official_actual_challenges_in_source} > {MAX_ACTUAL_CHALLENGES_PER_GAME})."
            )
        elif official_challenge_density > MAX_ACTUAL_CHALLENGE_DENSITY:
            actual_metrics_valid = False
            actual_metrics_reason = (
                "Suppressed: official challenge density exceeds threshold "
                f"({official_challenge_density:.1%} > {MAX_ACTUAL_CHALLENGE_DENSITY:.0%})."
            )
        elif actual_challenges_in_source > 0 and official_actual_challenges_in_source == 0:
            actual_metrics_valid = False
            actual_metrics_reason = "Suppressed: challenge rows exist without official lineage."
        elif savant_benchmark_comparison.get("status") == "mismatch":
            benchmark_total = savant_benchmark_comparison.get("benchmark_total_challenges")
            benchmark_rate = savant_benchmark_comparison.get("benchmark_overturn_rate")
            official_rate = savant_benchmark_comparison.get("official_overturn_rate")
            actual_metrics_reason = (
                "Official challenge coverage is partial versus the Baseball Savant ABS benchmark "
                f"({benchmark_total} benchmark challenges; internal overturn rate "
                f"{official_rate:.1%} vs {benchmark_rate:.1%})."
                if isinstance(benchmark_total, int)
                and isinstance(benchmark_rate, (int, float))
                and isinstance(official_rate, (int, float))
                else "Official challenge coverage is partial versus the Baseball Savant ABS benchmark."
            )

        official_rows_linked_to_replay = official_actual_challenges_in_source
        official_rows_collected_for_game = max(official_rows_collected_for_game, official_rows_linked_to_replay)
        official_rows_used_for_actual_metrics = official_rows_linked_to_replay if actual_metrics_valid else 0
        official_rows_suppressed = official_rows_linked_to_replay if not actual_metrics_valid and official_rows_linked_to_replay > 0 else 0
        official_rows_unmatched = max(0, official_rows_collected_for_game - official_rows_linked_to_replay)
        linkage_completeness_flag = _replay_linkage_completeness_flag(
            actual_metrics_valid=actual_metrics_valid,
            collected_rows=official_rows_collected_for_game,
            unmatched_rows=official_rows_unmatched,
            suppressed_rows=official_rows_suppressed,
            used_rows=official_rows_used_for_actual_metrics,
        )
        actual_sample_strength_flag = _replay_actual_sample_strength_flag(official_rows_used_for_actual_metrics)
        linkage_status = _replay_linkage_status(
            actual_metrics_valid=actual_metrics_valid,
            collected_rows=official_rows_collected_for_game,
            unmatched_rows=official_rows_unmatched,
            suppressed_rows=official_rows_suppressed,
            used_rows=official_rows_used_for_actual_metrics,
        )
        linkage_reason = _replay_linkage_reason(
            actual_metrics_valid=actual_metrics_valid,
            actual_metrics_reason=actual_metrics_reason,
            collected_rows=official_rows_collected_for_game,
            linked_rows=official_rows_linked_to_replay,
            unmatched_rows=official_rows_unmatched,
            suppressed_rows=official_rows_suppressed,
            used_rows=official_rows_used_for_actual_metrics,
        )

        summary = {
            "challenges_recommended": challenges_recommended,
            "successful_challenges": successful_challenges,
            "failed_challenges": failed_challenges,
            "positive_ev_holds": positive_ev_holds,
            "missed_opportunities": positive_ev_holds,
            "missed_positive_ev_opportunities": positive_ev_holds,
            "missed_overturns_hindsight": missed_overturns_hindsight,
            "missed_overturn_opportunities": missed_overturns_hindsight,
            "actual_challenges_in_source": official_actual_challenges_in_source if actual_metrics_valid else None,
            "actual_correct_challenges_in_source": actual_correct_challenges_in_source if actual_metrics_valid else None,
            "policy_actual_disagreements": policy_actual_disagreements if actual_metrics_valid else None,
            "policy_would_challenge_vs_actual_hold": policy_would_challenge_vs_actual_hold if actual_metrics_valid else None,
            "actual_challenged_vs_policy_hold": actual_challenged_vs_policy_hold if actual_metrics_valid else None,
            "counterfactual_delta_vs_actual": round(float(counterfactual_delta_vs_actual), 6) if actual_metrics_valid else None,
            "expected_run_value_added": round(float(cumulative_expected_policy_ev), 6),
            "run_value_added": round(float(cumulative_run_value), 6),
        }
        data_quality = {
            "actual_challenges_in_source": official_actual_challenges_in_source if actual_metrics_valid else 0,
            "actual_coverage_flag": (
                _replay_actual_coverage_flag(official_rows_used_for_actual_metrics)
                if actual_metrics_valid
                else "none"
            ),
            "linkage_completeness_flag": linkage_completeness_flag,
            "actual_sample_strength_flag": actual_sample_strength_flag,
            "actual_metrics_valid": actual_metrics_valid,
            "actual_metrics_reason": actual_metrics_reason,
            "official_actual_challenges_in_source": official_actual_challenges_in_source,
            "inferred_rows_present": inferred_rows_present,
            "scope_used": scope,
            "savant_benchmark_status": (
                str(savant_benchmark.get("status")) if savant_benchmark.get("status") is not None else None
            ),
            "benchmark_comparison_status": (
                str(savant_benchmark_comparison.get("status"))
                if savant_benchmark_comparison.get("status") is not None
                else None
            ),
            "benchmark_total_challenges": (
                int(savant_benchmark.get("total_challenges"))
                if isinstance(savant_benchmark.get("total_challenges"), (int, float))
                else None
            ),
            "benchmark_overturn_rate": (
                float(savant_benchmark.get("overturn_rate"))
                if isinstance(savant_benchmark.get("overturn_rate"), (int, float))
                else None
            ),
        }
        linkage_diagnostics = {
            "official_rows_collected_for_game": official_rows_collected_for_game,
            "official_rows_linked_to_replay": official_rows_linked_to_replay,
            "official_rows_unmatched": official_rows_unmatched,
            "official_rows_suppressed": official_rows_suppressed,
            "official_rows_used_for_actual_metrics": official_rows_used_for_actual_metrics,
            "linkage_status": linkage_status,
            "linkage_reason": linkage_reason,
        }
        payload = {
            "game": {
                "game_id": game_meta["game_id"],
                "date": game_meta["date"],
                "home_team": game_meta["home_team"],
                "away_team": game_meta["away_team"],
                "pitch_count": len(game_events),
                "scope_tag": replay_scope_tag(scope),
                "last_data_refresh_at": game_meta.get("last_data_refresh_at"),
                "source_max_game_date": game_meta.get("source_max_game_date"),
                "actual_challenges_in_source": official_actual_challenges_in_source if actual_metrics_valid else 0,
            },
            "pitches": pitches,
            "tracker": {
                "game_run_value_gained": summary["run_value_added"],
                "expected_policy_edge": summary["expected_run_value_added"],
                "realized_run_value": summary["run_value_added"],
                "challenges_recommended": challenges_recommended,
                "correct_challenges": successful_challenges,
                "positive_ev_holds": positive_ev_holds,
                "missed_opportunities": positive_ev_holds,
                "missed_positive_ev_opportunities": positive_ev_holds,
                "missed_overturns_hindsight": missed_overturns_hindsight,
                "missed_overturn_opportunities": missed_overturns_hindsight,
                "actual_challenges_in_source": official_actual_challenges_in_source if actual_metrics_valid else None,
                "actual_correct_challenges_in_source": actual_correct_challenges_in_source if actual_metrics_valid else None,
                "policy_actual_disagreements": policy_actual_disagreements if actual_metrics_valid else None,
                "counterfactual_delta_vs_actual": (
                    round(float(counterfactual_delta_vs_actual), 6) if actual_metrics_valid else None
                ),
            },
            "summary": summary,
            "definitions": {
                "expected_policy_edge": "Expected value from following policy versus never challenging.",
                "realized_run_value": "Realized run outcome from this historical pitch sequence under policy actions.",
                "positive_ev_holds": "Pitches where policy held despite small positive EV to preserve challenge value.",
                "missed_overturns_hindsight": "Overturnable holds seen only in hindsight; not a fair policy KPI.",
                "counterfactual_delta_vs_actual": "Difference between policy and on-field run value on disagreement pitches.",
            },
            "data_quality": data_quality,
            "linkage_diagnostics": linkage_diagnostics,
            "generated_at": _utc_now_iso(),
        }
        scope_cache[cache_key] = payload
        return payload

    def _refresh_replay_scope(
        scope: str,
        start_date: str | None = None,
        end_date: str | None = None,
        *,
        prewarm_local_caches: bool = True,
    ) -> dict[str, Any]:
        resolved_scope = _resolve_replay_scope(scope)
        try:
            refresh_meta = build_replay_dataset(
                settings=settings,
                scope=resolved_scope,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            failed_meta = {
                "status": "failed",
                "scope": resolved_scope,
                "scope_tag": replay_scope_tag(resolved_scope),
                "output_csv": _replay_csv_path(resolved_scope),
                "error": str(exc),
                "last_refresh_at": _utc_now_iso(),
            }
            STATE.replay_refresh_meta[resolved_scope] = failed_meta
            STATE.replay_dataset_stats_cache.pop(resolved_scope, None)
            raise HTTPException(status_code=500, detail=f"Replay refresh failed: {exc}") from exc

        STATE.replay_refresh_meta[resolved_scope] = refresh_meta
        _invalidate_replay_caches(resolved_scope)
        if prewarm_local_caches:
            try:
                # Prewarm the replay service and base catalog so the first replay load after
                # a dataset refresh does not pay the full cold-init cost inside the request path.
                active_service = _require_replay_service(resolved_scope)
                _build_games_catalog_base(resolved_scope, active_service)
                if not _load_ranked_games_catalog(resolved_scope):
                    _build_and_persist_ranked_catalog(resolved_scope, active_service)
                prewarm_stats = _prewarm_replay_payloads(resolved_scope, active_service)
                refresh_meta["payload_prewarm"] = prewarm_stats
                STATE.replay_refresh_meta[resolved_scope] = refresh_meta
            except Exception as exc:
                print(f"[abs-modal] replay prewarm failed for scope={resolved_scope}: {exc}")
        return refresh_meta

    def _build_replay_refresh_response(scope: str, refresh_meta: dict[str, Any]) -> dict[str, Any]:
        savant_backfill = refresh_meta.get("savant_statcast_backfill")
        if not isinstance(savant_backfill, dict):
            savant_backfill = {}
        refresh_status = str(refresh_meta.get("status") or "completed")
        return {
            "status": "accepted" if refresh_status == "running" else refresh_status,
            "scope": scope,
            "scope_tag": replay_scope_tag(scope),
            "replay_last_refresh_at": refresh_meta.get("last_refresh_at"),
            "replay_last_refresh_status": refresh_status,
            "replay_rows": refresh_meta.get("rows"),
            "replay_games": refresh_meta.get("games"),
            "replay_source_min_date": refresh_meta.get("source_min_game_date"),
            "replay_source_max_date": refresh_meta.get("source_max_game_date"),
            "output_csv": refresh_meta.get("output_csv"),
            "savant_backfill_missing_games": savant_backfill.get("missing_game_count"),
            "savant_backfill_fetched_games": savant_backfill.get("fetched_game_count"),
            "savant_backfill_failed_games": savant_backfill.get("failed_game_count"),
            "savant_backfill_rows": savant_backfill.get("backfill_row_count"),
        }

    def _start_background_replay_refresh(
        scope: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        resolved_scope = _resolve_replay_scope(scope)
        replay_path = _replay_csv_path(resolved_scope)
        existing_meta = _load_replay_refresh_meta(resolved_scope, replay_path).copy()
        if str(existing_meta.get("status") or "") == "running":
            # Guard against permanently-stuck "running" state: if the job has been
            # "running" for more than 40 minutes without completing, clear it so a
            # fresh job can be spawned. (Job container writes completion to Modal Dict;
            # if that write never happened the state is stale.)
            started_str = str(existing_meta.get("started_at") or "")
            stale = False
            if started_str:
                try:
                    from datetime import datetime, timezone as _tz
                    started_dt = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
                    age_minutes = (datetime.now(_tz.utc) - started_dt).total_seconds() / 60
                    stale = age_minutes > 90
                except Exception:
                    pass
            if not stale:
                return existing_meta
            print(f"[abs-modal] replay refresh meta for {resolved_scope} stuck in 'running' >40min — clearing")

        requested_at = _utc_now_iso()
        running_meta = _build_replay_refresh_status_payload(
            settings=settings,
            scope=resolved_scope,
            status="running",
            start_date=start_date,
            end_date=end_date,
            requested_at=requested_at,
            existing_meta=existing_meta,
        )
        STATE.replay_refresh_meta[resolved_scope] = running_meta
        write_replay_refresh_meta(replay_path, running_meta)
        # Write "running" to Dict BEFORE spawning so concurrent requests on other
        # containers see it immediately and don't spawn duplicate jobs.
        try:
            replay_catalog_store.put(f"meta:{resolved_scope}", running_meta)
        except Exception as _pre_spawn_exc:
            print(f"[abs-modal] pre-spawn Dict write failed: {_pre_spawn_exc}")
        try:
            job = replay_refresh_job.spawn(
                scope=resolved_scope,
                start_date=start_date,
                end_date=end_date,
                requested_at=requested_at,
            )
            running_meta["job_id"] = getattr(job, "object_id", None)
            STATE.replay_refresh_meta[resolved_scope] = running_meta
            write_replay_refresh_meta(replay_path, running_meta)
            print(
                f"[abs-modal] enqueued replay refresh job scope={resolved_scope} "
                f"call_id={getattr(job, 'object_id', 'unknown')}"
            )
        except Exception as exc:
            failed_meta = _build_replay_refresh_status_payload(
                settings=settings,
                scope=resolved_scope,
                status="failed",
                start_date=start_date,
                end_date=end_date,
                requested_at=requested_at,
                last_refresh_at=_utc_now_iso(),
                error=str(exc),
                existing_meta=existing_meta,
            )
            STATE.replay_refresh_meta[resolved_scope] = failed_meta
            write_replay_refresh_meta(replay_path, failed_meta)
            print(f"[abs-modal] failed to enqueue replay refresh job scope={resolved_scope}: {exc}")
            raise HTTPException(status_code=500, detail=f"Replay refresh enqueue failed: {exc}") from exc
        return running_meta

    def _get_latest_stress_row_with_timeout(timeout_seconds: float = 3.0) -> dict[str, Any] | None:
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            if hasattr(repo, "get_recent_stress_test_runs"):
                future = executor.submit(repo.get_recent_stress_test_runs, 8)
            else:
                future = executor.submit(repo.get_latest_stress_test_run)
            try:
                rows = future.result(timeout=timeout_seconds)
                if isinstance(rows, list):
                    return _select_preferred_stress_row(rows)
                if isinstance(rows, dict):
                    return rows
                return None
            except FuturesTimeoutError:
                print(f"[abs-modal] get_latest_stress_test_run timed out after {timeout_seconds}s; falling back")
                return None
            except Exception as exc:
                print(f"[abs-modal] get_latest_stress_test_run failed: {exc}")
                return None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _get_latest_full_matrix_stress_row_with_timeout(timeout_seconds: float = 3.0) -> dict[str, Any] | None:
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            if hasattr(repo, "get_recent_stress_test_runs"):
                future = executor.submit(repo.get_recent_stress_test_runs, 12)
            else:
                future = executor.submit(repo.get_latest_stress_test_run)
            try:
                rows = future.result(timeout=timeout_seconds)
                if isinstance(rows, list):
                    return _select_preferred_stress_row(rows, artifact_mode=ARTIFACT_MODE_FULL_MATRIX)
                if isinstance(rows, dict) and _stress_row_matches_artifact_mode(rows, ARTIFACT_MODE_FULL_MATRIX):
                    return rows
                return None
            except FuturesTimeoutError:
                print(f"[abs-modal] get_latest_full_matrix_stress_row timed out after {timeout_seconds}s; falling back")
                return None
            except Exception as exc:
                print(f"[abs-modal] get_latest_full_matrix_stress_row failed: {exc}")
                return None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _stress_row_artifact_mode(row: dict[str, Any]) -> str:
        summary = _coerce_dict(row.get("summary"))
        artifact_mode = str(summary.get("artifact_mode") or "").strip()
        if artifact_mode in {ARTIFACT_MODE_FAST_BASE, ARTIFACT_MODE_FULL_MATRIX}:
            return artifact_mode
        scenario_outcomes = summary.get("scenario_outcomes")
        if isinstance(scenario_outcomes, list) and len(scenario_outcomes) <= 1:
            return ARTIFACT_MODE_FAST_BASE
        return ARTIFACT_MODE_FULL_MATRIX

    def _stress_row_valid(row: dict[str, Any]) -> bool:
        summary = _coerce_dict(row.get("summary"))
        scenario_outcomes = summary.get("scenario_outcomes")
        return isinstance(scenario_outcomes, list) and len(scenario_outcomes) > 0

    def _stress_row_matches_artifact_mode(row: dict[str, Any], artifact_mode: str | None) -> bool:
        if artifact_mode is None:
            return True
        row_mode = _stress_row_artifact_mode(row)
        if artifact_mode == ARTIFACT_MODE_FULL_MATRIX:
            return row_mode == ARTIFACT_MODE_FULL_MATRIX
        return row_mode == artifact_mode

    def _select_preferred_stress_row(
        rows: list[dict[str, Any]],
        artifact_mode: str | None = None,
    ) -> dict[str, Any] | None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not _stress_row_valid(row):
                continue
            if not _stress_row_matches_artifact_mode(row, artifact_mode):
                continue
            return row
        return None

    def _get_recompute_status_snapshot(artifact_mode: str) -> dict[str, Any]:
        mode = _artifact_mode_label(artifact_mode)
        snapshot = _default_recompute_status(mode)
        existing = STATE.recompute_status.get(mode)
        if isinstance(existing, dict):
            snapshot.update(existing)
        shared = _load_shared_recompute_status(mode)
        if isinstance(shared, dict):
            snapshot.update(shared)
        future = STATE.recompute_futures.get(mode)
        snapshot["active"] = bool(snapshot.get("status") == "running")
        if future is not None and not future.done():
            snapshot["active"] = True
        if snapshot["active"]:
            snapshot["status"] = "running"
        return snapshot

    def _set_recompute_status(
        artifact_mode: str,
        *,
        status: str,
        requested_at: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        latest_generated_at: str | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        mode = _artifact_mode_label(artifact_mode)
        current = _get_recompute_status_snapshot(mode)
        current["artifact_mode"] = mode
        current["status"] = status
        current["active"] = status == "running"
        if status == "running":
            current["completed_at"] = None
            if started_at is None and requested_at is not None:
                current["started_at"] = None
        if requested_at is not None:
            current["requested_at"] = requested_at
        if started_at is not None:
            current["started_at"] = started_at
        if completed_at is not None:
            current["completed_at"] = completed_at
        if latest_generated_at is not None:
            current["latest_generated_at"] = latest_generated_at
        if last_error is not None or status == "failed":
            current["last_error"] = last_error
        elif status in {"completed", "running"}:
            current["last_error"] = None
        STATE.recompute_status[mode] = current
        _persist_shared_recompute_status(current)
        return dict(current)

    def _hydrate_stress_result_from_row(row: dict[str, Any]) -> dict[str, Any]:
        result = _result_from_stored_row(
            row,
            repo=repo,
            settings=settings,
            stress_policy_config=stress_policy_config,
        )
        _hydrate_cached_ui_artifacts_from_row(row)
        run_at = row.get("run_at")
        if run_at:
            run_at_str = str(run_at)
            STATE.last_stress_test_at = run_at_str
            STATE.last_retrain_at = run_at_str
        STATE.latest_result = result
        row_mode = _stress_row_artifact_mode(row)
        current_status = _get_recompute_status_snapshot(row_mode)
        requested_at = _parse_iso_datetime(str(current_status.get("requested_at") or None))
        row_generated_at = _parse_iso_datetime(_stress_result_generated_at(result))
        if not (
            current_status.get("status") == "running"
            and requested_at is not None
            and row_generated_at is not None
            and requested_at > row_generated_at
        ):
            _set_recompute_status(
                row_mode,
                status="completed",
                completed_at=str(run_at) if run_at is not None else None,
                latest_generated_at=_stress_result_generated_at(result),
            )
        return result

    def _get_latest_ingestion_row_with_timeout(timeout_seconds: float = 2.0) -> dict[str, Any] | None:
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(repo.get_latest_ingestion_run)
            try:
                return future.result(timeout=timeout_seconds)
            except FuturesTimeoutError:
                print(f"[abs-modal] get_latest_ingestion_run timed out after {timeout_seconds}s; falling back")
                return None
            except Exception as exc:
                print(f"[abs-modal] get_latest_ingestion_run failed: {exc}")
                return None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _extract_outcomes_metrics(latest_ingestion: dict[str, Any] | None) -> dict[str, Any]:
        def _summarize_outcomes_uri(outcomes_uri: str) -> dict[str, Any]:
            try:
                request = UrlRequest(
                    outcomes_uri,
                    method="GET",
                    headers={"User-Agent": "the-brain-abs/1.0"},
                )
                with urlopen(request, timeout=4.0) as response:
                    text = response.read().decode("utf-8", errors="ignore")
            except Exception:
                return {}

            total_rows = 0
            overturned_rows = 0
            upheld_rows = 0
            official_rows = 0
            inferred_rows = 0
            min_ts: datetime | None = None
            max_ts: datetime | None = None
            official_max_ts: datetime | None = None
            for row in csv.DictReader(io.StringIO(text)):
                lineage = str(row.get("outcome_source_type", "")).strip().lower()
                if lineage == "official" or not lineage:
                    official_rows += 1
                elif lineage == "inferred":
                    inferred_rows += 1
                challenge_result = str(row.get("challenge_result", "")).strip().lower()
                if challenge_result not in {"overturned", "upheld", "stands"}:
                    continue
                total_rows += 1
                if challenge_result == "overturned":
                    overturned_rows += 1
                else:
                    upheld_rows += 1

                ts_raw = str(row.get("challenge_initiated_ts", "")).strip()
                if not ts_raw:
                    continue
                try:
                    parsed = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                except Exception:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                parsed = parsed.astimezone(timezone.utc)
                min_ts = parsed if min_ts is None or parsed < min_ts else min_ts
                max_ts = parsed if max_ts is None or parsed > max_ts else max_ts
                if lineage in {"official", ""}:
                    official_max_ts = parsed if official_max_ts is None or parsed > official_max_ts else official_max_ts

            overturn_rate = (overturned_rows / total_rows) if total_rows > 0 else None
            if official_rows > 0 and inferred_rows > 0:
                lineage_status = "mixed"
            elif official_rows > 0:
                lineage_status = "official_only"
            elif inferred_rows > 0:
                lineage_status = "inferred_only"
            else:
                lineage_status = "official_only"
            return {
                "overturn_rate": round(overturn_rate, 6) if overturn_rate is not None else None,
                "overturned_rows": overturned_rows,
                "upheld_rows": upheld_rows,
                "min_challenge_ts": min_ts.isoformat().replace("+00:00", "Z") if min_ts else None,
                "max_challenge_ts": max_ts.isoformat().replace("+00:00", "Z") if max_ts else None,
                "official_rows": official_rows,
                "inferred_rows": inferred_rows,
                "outcomes_lineage_status": lineage_status,
                "official_max_challenge_ts": (
                    official_max_ts.isoformat().replace("+00:00", "Z") if official_max_ts else None
                ),
            }

        if not latest_ingestion:
            return {
                "status": None,
                "run_at": None,
                "row_count": None,
                "match_rate": None,
                "fingerprint_prefix": None,
                "overturn_rate": None,
                "overturned_rows": None,
                "upheld_rows": None,
                "min_challenge_ts": None,
                "max_challenge_ts": None,
                "official_rows": None,
                "inferred_rows": None,
                "official_match_rate": None,
                "outcomes_lineage_status": None,
                "official_max_challenge_ts": None,
                "savant_benchmark_status": None,
                "savant_benchmark_last_refresh_at": None,
                "savant_benchmark_years": None,
                "savant_benchmark_total_challenges": None,
                "savant_benchmark_total_overturns": None,
                "savant_benchmark_overturn_rate": None,
                "savant_benchmark_challenge_delta": None,
                "savant_benchmark_challenge_delta_pct": None,
                "savant_benchmark_overturn_rate_delta": None,
                "savant_benchmark_comparison_status": None,
                "explicit_used": False,
            }

        details = latest_ingestion.get("details")
        if not isinstance(details, dict):
            details = {}
        transform_stats = details.get("transform_stats") if isinstance(details.get("transform_stats"), dict) else {}

        status = details.get("outcomes_status")
        if not status:
            status = latest_ingestion.get("status")

        run_at = latest_ingestion.get("run_at")
        run_at_str = str(run_at) if run_at is not None else None

        row_count = details.get("outcomes_row_count")
        try:
            row_count = int(row_count) if row_count is not None else None
        except Exception:
            row_count = None

        match_rate = details.get("outcomes_match_rate")
        try:
            match_rate = float(match_rate) if match_rate is not None else None
        except Exception:
            match_rate = None

        fingerprint = details.get("outcomes_fingerprint")
        fingerprint_prefix = fingerprint[:8] if isinstance(fingerprint, str) and fingerprint else None
        outcomes_reference = details.get("outcomes_reference")
        if not isinstance(outcomes_reference, dict):
            outcomes_reference = {}
        if not outcomes_reference and settings.abs_challenge_outcomes_uri:
            outcomes_reference = _summarize_outcomes_uri(settings.abs_challenge_outcomes_uri)

        official_outcomes_uri = details.get("official_outcomes_uri")
        if not isinstance(official_outcomes_uri, str) or not official_outcomes_uri.strip():
            official_outcomes_uri = (
                settings.abs_official_challenge_outcomes_uri or settings.abs_challenge_outcomes_uri
            )
        official_reference: dict[str, Any] = {}
        if official_outcomes_uri:
            official_reference = _summarize_outcomes_uri(official_outcomes_uri)

        official_rows = (
            official_reference.get("official_rows")
            if isinstance(official_reference, dict) and official_reference.get("official_rows") is not None
            else outcomes_reference.get("official_rows")
        )
        inferred_rows = (
            official_reference.get("inferred_rows")
            if isinstance(official_reference, dict) and official_reference.get("inferred_rows") is not None
            else outcomes_reference.get("inferred_rows")
        )
        official_match_rate = details.get("official_outcomes_match_rate")
        if official_match_rate is None:
            official_match_rate = transform_stats.get("official_match_rate")
        try:
            official_match_rate = float(official_match_rate) if official_match_rate is not None else None
        except Exception:
            official_match_rate = None
        outcomes_lineage_status = details.get("outcomes_lineage_status")
        if outcomes_lineage_status is None and isinstance(outcomes_reference, dict):
            outcomes_lineage_status = outcomes_reference.get("outcomes_lineage_status")
        outcomes_lineage_status = str(outcomes_lineage_status) if outcomes_lineage_status is not None else None
        outcomes_official_collector = details.get("outcomes_official_collector")
        if not isinstance(outcomes_official_collector, dict):
            outcomes_official_collector = {}
        official_upload = (
            outcomes_official_collector.get("official_upload")
            if isinstance(outcomes_official_collector.get("official_upload"), dict)
            else {}
        )
        official_max_challenge_ts = None
        for candidate in (
            official_reference.get("official_max_challenge_ts")
            if isinstance(official_reference, dict)
            else None,
            official_upload.get("official_max_challenge_ts"),
            outcomes_official_collector.get("official_max_challenge_ts"),
            outcomes_reference.get("official_max_challenge_ts") if isinstance(outcomes_reference, dict) else None,
        ):
            if candidate is not None and str(candidate).strip():
                official_max_challenge_ts = str(candidate)
                break
        official_max_challenge_ts = str(official_max_challenge_ts) if official_max_challenge_ts is not None else None
        savant_benchmark = details.get("savant_abs_benchmark")
        if not isinstance(savant_benchmark, dict):
            savant_benchmark = {}
        savant_benchmark_comparison = details.get("savant_abs_benchmark_comparison")
        if not isinstance(savant_benchmark_comparison, dict):
            savant_benchmark_comparison = {}

        overturn_rate = outcomes_reference.get("overturn_rate")
        try:
            overturn_rate = float(overturn_rate) if overturn_rate is not None else None
        except Exception:
            overturn_rate = None

        overturned_rows = outcomes_reference.get("overturned_rows")
        try:
            overturned_rows = int(overturned_rows) if overturned_rows is not None else None
        except Exception:
            overturned_rows = None

        upheld_rows = outcomes_reference.get("upheld_rows")
        try:
            upheld_rows = int(upheld_rows) if upheld_rows is not None else None
        except Exception:
            upheld_rows = None

        min_challenge_ts = outcomes_reference.get("min_challenge_ts")
        min_challenge_ts = str(min_challenge_ts) if min_challenge_ts is not None else None

        max_challenge_ts = outcomes_reference.get("max_challenge_ts")
        max_challenge_ts = str(max_challenge_ts) if max_challenge_ts is not None else None

        return {
            "status": status,
            "run_at": run_at_str,
            "row_count": row_count,
            "match_rate": match_rate,
            "fingerprint_prefix": fingerprint_prefix,
            "overturn_rate": overturn_rate,
            "overturned_rows": overturned_rows,
            "upheld_rows": upheld_rows,
            "min_challenge_ts": min_challenge_ts,
            "max_challenge_ts": max_challenge_ts,
            "official_rows": int(official_rows) if isinstance(official_rows, (int, float)) else None,
            "inferred_rows": int(inferred_rows) if isinstance(inferred_rows, (int, float)) else None,
            "official_match_rate": official_match_rate,
            "outcomes_lineage_status": outcomes_lineage_status,
            "official_max_challenge_ts": official_max_challenge_ts,
            "savant_benchmark_status": (
                str(savant_benchmark.get("status")) if savant_benchmark.get("status") is not None else None
            ),
            "savant_benchmark_last_refresh_at": (
                str(savant_benchmark.get("fetched_at")) if savant_benchmark.get("fetched_at") is not None else None
            ),
            "savant_benchmark_years": savant_benchmark.get("years"),
            "savant_benchmark_total_challenges": (
                int(savant_benchmark.get("total_challenges"))
                if isinstance(savant_benchmark.get("total_challenges"), (int, float))
                else None
            ),
            "savant_benchmark_total_overturns": (
                int(savant_benchmark.get("total_overturns"))
                if isinstance(savant_benchmark.get("total_overturns"), (int, float))
                else None
            ),
            "savant_benchmark_overturn_rate": (
                float(savant_benchmark.get("overturn_rate"))
                if isinstance(savant_benchmark.get("overturn_rate"), (int, float))
                else None
            ),
            "savant_benchmark_challenge_delta": (
                int(savant_benchmark_comparison.get("challenge_delta"))
                if isinstance(savant_benchmark_comparison.get("challenge_delta"), (int, float))
                else None
            ),
            "savant_benchmark_challenge_delta_pct": (
                float(savant_benchmark_comparison.get("challenge_delta_pct"))
                if isinstance(savant_benchmark_comparison.get("challenge_delta_pct"), (int, float))
                else None
            ),
            "savant_benchmark_overturn_rate_delta": (
                float(savant_benchmark_comparison.get("overturn_rate_delta"))
                if isinstance(savant_benchmark_comparison.get("overturn_rate_delta"), (int, float))
                else None
            ),
            "savant_benchmark_comparison_status": (
                str(savant_benchmark_comparison.get("status"))
                if savant_benchmark_comparison.get("status") is not None
                else None
            ),
            "official_savant_detail_rows_by_year": (
                outcomes_official_collector.get("detail_rows_by_year")
                if isinstance(outcomes_official_collector.get("detail_rows_by_year"), dict)
                else None
            ),
            "official_savant_matched_rows_by_year": (
                outcomes_official_collector.get("matched_rows_by_year")
                if isinstance(outcomes_official_collector.get("matched_rows_by_year"), dict)
                else None
            ),
            "official_savant_unmatched_rows_by_year": (
                outcomes_official_collector.get("unmatched_rows_by_year")
                if isinstance(outcomes_official_collector.get("unmatched_rows_by_year"), dict)
                else None
            ),
            "official_savant_unmatched_reason_counts": (
                outcomes_official_collector.get("unmatched_reason_counts")
                if isinstance(outcomes_official_collector.get("unmatched_reason_counts"), dict)
                else None
            ),
            "official_savant_unmatched_reason_counts_by_year": (
                outcomes_official_collector.get("unmatched_reason_counts_by_year")
                if isinstance(outcomes_official_collector.get("unmatched_reason_counts_by_year"), dict)
                else None
            ),
            "explicit_used": bool(details.get("explicit_used", False)),
        }

    def _memo_outcomes_warnings(latest_ingestion: dict[str, Any] | None) -> list[str]:
        if not settings.abs_challenge_outcomes_uri:
            return []

        warnings: list[str] = []
        outcomes_metrics = _extract_outcomes_metrics(latest_ingestion)
        status = str(outcomes_metrics.get("status") or "")
        match_rate = outcomes_metrics.get("match_rate")
        explicit_used = bool(outcomes_metrics.get("explicit_used", False))

        if not latest_ingestion:
            warnings.append("Explicit ABS outcomes feed has not produced an ingestion run yet.")
            return warnings

        if not explicit_used:
            warnings.append("Latest analysis did not use explicit ABS challenge outcomes; results may rely on proxy inference.")

        if isinstance(match_rate, float) and match_rate < settings.abs_min_outcome_match_rate:
            warnings.append(
                f"Explicit outcomes match rate ({match_rate:.2f}) is below configured threshold "
                f"({settings.abs_min_outcome_match_rate:.2f})."
            )

        if status.startswith("failed_outcomes") or status in {"missing_uri", "stale"}:
            warnings.append(f"Latest outcomes ingestion status: {status}.")

        deduped: list[str] = []
        for warning in warnings:
            if warning not in deduped:
                deduped.append(warning)
        return deduped

    def _official_outcomes_breakdown_payload(team: str | None = None) -> dict[str, Any]:
        outcomes_uri = settings.abs_official_challenge_outcomes_uri or settings.abs_challenge_outcomes_uri
        if not outcomes_uri:
            raise HTTPException(status_code=503, detail="Official outcomes source is not configured")

        metadata_uri = derive_official_metadata_public_uri(outcomes_uri)
        payload = build_official_outcomes_breakdown(
            outcomes_source=outcomes_uri,
            local_metadata_sources=OFFICIAL_OUTCOMES_LOCAL_METADATA_PATHS,
            supplemental_metadata_source=metadata_uri,
            timeout=8.0,
            team=team,
        )
        payload["sources"] = {
            "official_outcomes_uri": outcomes_uri,
            "official_outcomes_metadata_uri": metadata_uri,
            "local_metadata_candidates": OFFICIAL_OUTCOMES_LOCAL_METADATA_PATHS,
        }
        return payload

    def _filtered_audit_cache_key(scope: str, team: str | None, year: str | None, game_type: str | None = None) -> str:
        parts = [f"v3:scope:{scope}"]
        if team:
            parts.append(f"team:{team.strip().upper()}")
        if year:
            parts.append(f"year:{year.strip()}")
        if game_type:
            parts.append(f"gt:{game_type.strip().upper()}")
        return ":".join(parts)

    # Known MLB Opening Day dates per year (first day of Regular Season).
    # Used by _filter_catalog_by_game_type since game_type is not stored in the replay CSV.
    _OPENING_DAY: dict[str, str] = {
        "2025": "2025-03-27",
        "2026": "2026-03-25",  # Opening Night (Netflix): Yankees vs Giants; broader slate March 26
    }
    _OPENING_DAY_DEFAULT_MMDD = "03-27"

    def _filter_catalog_by_game_type(catalog: list[dict[str, Any]], game_type: str) -> list[dict[str, Any]]:
        """Filter catalog entries by game type using date-based heuristic.
        Uses known Opening Day dates per year; falls back to March 27 for unknown years.
        """
        gt = game_type.strip().upper()
        if gt not in ("R", "S"):
            return catalog
        result = []
        for g in catalog:
            d = str(g.get("date", ""))
            if len(d) < 4:
                continue
            yr = d[:4]
            threshold = _OPENING_DAY.get(yr, f"{yr}-{_OPENING_DAY_DEFAULT_MMDD}")
            if gt == "R" and d >= threshold:
                result.append(g)
            elif gt == "S" and d < threshold:
                result.append(g)
        return result

    def _actual_vs_policy_summary_payload(scope: str, *, team: str | None = None, year: str | None = None, game_type: str | None = None) -> dict[str, Any]:
        resolved_scope = _resolve_replay_scope(scope)
        is_filtered = bool(team or year or game_type)
        # Use scoped cache key — filtered requests get their own entry, never overwrite global
        cache_key = _filtered_audit_cache_key(resolved_scope, team, year, game_type) if is_filtered else _replay_audit_summary_key(resolved_scope)
        payload = _get_replay_audit_summary(resolved_scope) if not is_filtered else None
        if is_filtered:
            try:
                payload = replay_audit_summary_store.get(cache_key)
            except KeyError:
                payload = None
            except Exception:
                payload = None
        if payload is None:
            catalog = _load_ranked_games_catalog(resolved_scope)
            if not catalog and is_filtered:
                # No ranked catalog in memory or Modal Dict. For filtered requests, build
                # simulation results for only the matching games instead of all ~2600 —
                # this completes within the request timeout (typically 12 games vs 2602).
                try:
                    base_catalog = _build_games_catalog_base_from_csv(resolved_scope)
                except Exception:
                    base_catalog = []
                if base_catalog:
                    filtered_base = base_catalog
                    if team:
                        team_upper = team.strip().upper()
                        filtered_base = [g for g in filtered_base if str(g.get("home_team", "")).strip().upper() == team_upper or str(g.get("away_team", "")).strip().upper() == team_upper]
                    if year:
                        filtered_base = [g for g in filtered_base if str(g.get("date", "")).startswith(year)]
                    if game_type:
                        filtered_base = _filter_catalog_by_game_type(filtered_base, game_type)
                    if filtered_base:
                        try:
                            # Load replay service once (reads CSV into memory, cached after first call)
                            active_service = _require_replay_service(resolved_scope)
                            # Build base catalog from the in-memory service — avoids second CSV read
                            full_base = _build_games_catalog_base(resolved_scope, active_service)
                            # Re-apply team/year/game_type filter on the service-derived catalog
                            filtered_base = full_base
                            if team:
                                t_upper = team.strip().upper()
                                filtered_base = [g for g in filtered_base if str(g.get("home_team", "")).strip().upper() == t_upper or str(g.get("away_team", "")).strip().upper() == t_upper]
                            if year:
                                filtered_base = [g for g in filtered_base if str(g.get("date", "")).startswith(year)]
                            if game_type:
                                filtered_base = _filter_catalog_by_game_type(filtered_base, game_type)
                            refresh_meta = _load_replay_refresh_meta(resolved_scope, _replay_csv_path(resolved_scope))
                            official_counts_by_game = _load_official_challenge_counts_by_game()
                            latest_ingestion = _get_latest_ingestion_row_with_timeout(timeout_seconds=2.0)
                            latest_ingestion_details = latest_ingestion.get("details") if isinstance(latest_ingestion, dict) else None
                            if not isinstance(latest_ingestion_details, dict):
                                latest_ingestion_details = {}
                            # Index events by game_id for fast lookup
                            filtered_game_ids = {str(g.get("game_id", "")) for g in filtered_base}
                            events_by_game: dict[str, list[Any]] = {}
                            for event in active_service.events:
                                gid = str(event.game_id)
                                if gid in filtered_game_ids:
                                    events_by_game.setdefault(gid, []).append(event)
                            for evlist in events_by_game.values():
                                evlist.sort(key=_pitch_sort_key)
                            scope_stats_cache = STATE.replay_game_stats_cache.setdefault(resolved_scope, {})
                            catalog = []
                            for game in filtered_base:
                                game_id = str(game.get("game_id", "")).strip()
                                if not game_id:
                                    continue
                                game_events = events_by_game.get(game_id)
                                if not game_events:
                                    continue
                                pt_upper = team.strip().upper() if team else None
                                stats_key = f"{game_id}::{pt_upper}" if pt_upper else game_id
                                stats = scope_stats_cache.get(stats_key)
                                if stats is None:
                                    stats = _compute_game_stats_for_catalog(
                                        resolved_scope, active_service, game_id, game,
                                        game_events, refresh_meta, official_counts_by_game,
                                        latest_ingestion_details,
                                        policy_team=pt_upper,
                                    )
                                    scope_stats_cache[stats_key] = stats
                                enriched = dict(game)
                                enriched.update(stats)
                                catalog.append(enriched)
                        except Exception as exc:
                            print(f"[abs-modal] filtered catalog simulation failed: {exc}")
                            catalog = []
            if not catalog and not is_filtered:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Replay actual-vs-policy summary is unavailable because no replay dataset "
                        "is present for this scope. Run /v1/replay/refresh first."
                    ),
                )
            if not catalog:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "No replay data found for the requested team/year. "
                        "Ensure a replay refresh has been run with data covering the selected season."
                    ),
                )
            if team and catalog:
                team_upper = team.strip().upper()
                catalog = [g for g in catalog if str(g.get("home_team", "")).strip().upper() == team_upper or str(g.get("away_team", "")).strip().upper() == team_upper]
            if year and catalog:
                catalog = [g for g in catalog if str(g.get("date", "")).startswith(year)]
            if game_type and catalog:
                catalog = _filter_catalog_by_game_type(catalog, game_type)
            replay_dataset_stats = _replay_dataset_stats(resolved_scope)
            payload = build_actual_vs_policy_summary(
                catalog=catalog,
                official_summary={},
                replay_dataset_stats=replay_dataset_stats,
                scope=resolved_scope,
            )
            # Cache both unfiltered (global key) and filtered (scoped key) results
            if not is_filtered:
                _set_replay_audit_summary(resolved_scope, payload)
            else:
                try:
                    replay_audit_summary_store.put(cache_key, payload)
                except Exception as exc:
                    print(f"[abs-modal] failed to cache filtered audit summary for {cache_key}: {exc}")
        latest_ingestion = _get_latest_ingestion_row_with_timeout(timeout_seconds=2.0)
        outcomes_metrics = _extract_outcomes_metrics(latest_ingestion)
        payload = dict(payload)
        source_summary = dict(payload.get("source_summary") or {})
        source_summary.update(
            {
                "official_rows_total": (
                    int(outcomes_metrics.get("official_rows"))
                    if isinstance(outcomes_metrics.get("official_rows"), (int, float))
                    else 0
                ),
                "official_overturned_rows": (
                    int(outcomes_metrics.get("overturned_rows"))
                    if isinstance(outcomes_metrics.get("overturned_rows"), (int, float))
                    else 0
                ),
                "official_overturn_rate": (
                    float(outcomes_metrics.get("overturn_rate"))
                    if isinstance(outcomes_metrics.get("overturn_rate"), (int, float))
                    else None
                ),
                "official_window_start": (
                    str(outcomes_metrics.get("min_challenge_ts"))
                    if outcomes_metrics.get("min_challenge_ts") is not None
                    else None
                ),
                "official_window_end": (
                    str(outcomes_metrics.get("max_challenge_ts"))
                    if outcomes_metrics.get("max_challenge_ts") is not None
                    else None
                ),
                "official_lineage_status": (
                    str(outcomes_metrics.get("outcomes_lineage_status"))
                    if outcomes_metrics.get("outcomes_lineage_status") is not None
                    else None
                ),
            }
        )
        payload["source_summary"] = source_summary
        payload["sources"] = {
            "scope_tag": replay_scope_tag(resolved_scope),
            "ranked_catalog_source": _replay_csv_path(resolved_scope).replace(".csv", ".catalog.json"),
            "replay_output_csv": _replay_csv_path(resolved_scope),
            "official_outcomes_uri": settings.abs_official_challenge_outcomes_uri or settings.abs_challenge_outcomes_uri,
        }
        return payload

    def _build_game_recap(payload: dict[str, Any], *, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any]:
        """Build a structured game recap from a stored replay payload."""
        game = dict(payload.get("game") or {})
        game_id = str(game.get("game_id") or "")
        if game_id:
            official_score = _load_pitching_official_game_score(game_id, league=league)
            if isinstance(official_score, dict):
                official_home = official_score.get("home_score")
                official_away = official_score.get("away_score")
                if official_home is not None and official_away is not None:
                    game["final_home_score"] = official_home
                    game["final_away_score"] = official_away
                    game["home_team"] = official_score.get("home_team") or game.get("home_team")
                    game["away_team"] = official_score.get("away_team") or game.get("away_team")
                    payload = {**payload, "game": game}
        game_meta = _load_pitching_game_meta(game_id, league=league) if game_id else {}
        if game_id and isinstance(game_meta, dict):
            official_boxscore = _load_pitching_official_boxscore(game_id, league=league)
            if official_boxscore:
                merged_meta = dict(game_meta)
                merged_meta["official_pitching_boxscore"] = official_boxscore
                game_meta = merged_meta
        pitch_facts = _load_pitching_official_pitch_facts(game_id, league=league) if game_id else None
        return build_pitching_postgame_report(
            payload,
            game_meta=game_meta if isinstance(game_meta, dict) else {},
            pitch_fact_payload=pitch_facts if isinstance(pitch_facts, dict) else None,
        )

    def _pitching_recap_settings_key(*, league: str = DEFAULT_PITCHING_LEAGUE) -> str:
        normalized_league = _normalize_pitching_league(league)
        return f"settings:{normalized_league}"

    def _sanitize_pitching_recap_settings(raw: dict[str, Any]) -> dict[str, Any]:
        def _normalized_team_list(values: Any) -> list[str]:
            normalized: list[str] = []
            for item in values or []:
                team = _normalize_pitching_recap_team(item)
                if team and team not in normalized:
                    normalized.append(team)
            return normalized

        recap_teams = _normalized_team_list(raw.get("recap_teams") or raw.get("enabled_teams") or [])
        auto_email_source = raw.get("auto_email_teams") or recap_teams
        auto_email_teams = [team for team in _normalized_team_list(auto_email_source) if team in recap_teams]
        finalized_email_source = raw.get("finalized_email_teams") or auto_email_teams
        finalized_email_teams = [team for team in _normalized_team_list(finalized_email_source) if team in auto_email_teams]

        raw_team_recipients = raw.get("team_recipients") or {}
        team_recipients: dict[str, list[str]] = {}
        if isinstance(raw_team_recipients, dict):
            for team in recap_teams:
                values = (
                    raw_team_recipients.get(team)
                    or raw_team_recipients.get(team.lower())
                    or raw_team_recipients.get(team.upper())
                    or []
                )
                recipients = _normalize_recipients(values)
                if recipients:
                    team_recipients[team] = recipients

        return {
            "recap_teams": recap_teams,
            "auto_email_teams": auto_email_teams,
            "finalized_email_teams": finalized_email_teams,
            "enabled_teams": recap_teams,
            "team_recipients": team_recipients,
        }

    def _shared_pitcher_intel_email_settings() -> dict[str, Any]:
        raw = _modal_dict_get(shared_pitcher_intel_settings_store, "settings", {}) or {}
        if not isinstance(raw, dict):
            raw = {}
        raw_team_recipients = raw.get("team_recipients") or {}
        team_recipients: dict[str, list[str]] = {}
        if isinstance(raw_team_recipients, dict):
            for raw_team, raw_values in raw_team_recipients.items():
                normalized_team = _normalize_pitching_recap_team(raw_team)
                recipients = _normalize_recipients(raw_values)
                if normalized_team and recipients:
                    team_recipients[normalized_team] = recipients
        return {
            "email_provider": _normalize_pitching_recap_email_provider(raw.get("email_provider")),
            "resend_api_key": str(raw.get("resend_api_key") or "").strip(),
            "smtp_host": str(raw.get("smtp_host") or "").strip(),
            "smtp_port": _smtp_port_value(raw.get("smtp_port")),
            "smtp_username": str(raw.get("smtp_username") or "").strip(),
            "smtp_password": str(raw.get("smtp_password") or ""),
            "smtp_from_name": str(raw.get("smtp_from_name") or "brAIn").strip() or "brAIn",
            "smtp_from_email": str(raw.get("smtp_from_email") or "").strip(),
            "team_recipients": team_recipients,
        }

    def _pitching_recap_email_delivery_error(settings: dict[str, Any]) -> str:
        provider = _normalize_pitching_recap_email_provider((settings or {}).get("email_provider"))
        if provider == "smtp":
            required = {
                "smtp_host": str((settings or {}).get("smtp_host") or "").strip(),
                "smtp_username": str((settings or {}).get("smtp_username") or "").strip(),
                "smtp_password": str((settings or {}).get("smtp_password") or "").strip(),
                "smtp_from_email": str((settings or {}).get("smtp_from_email") or "").strip(),
            }
            missing = [label.replace("smtp_", "") for label, value in required.items() if not value]
            if missing:
                return f"Send failed: SMTP not configured ({', '.join(missing)} missing)"
            return ""
        if not str((settings or {}).get("resend_api_key") or "").strip():
            return "Send failed: no Resend API key configured"
        return ""

    def _pitching_recap_settings_public_payload(
        raw: dict[str, Any] | None,
        *,
        league: str = DEFAULT_PITCHING_LEAGUE,
    ) -> dict[str, Any]:
        sanitized = _sanitize_pitching_recap_settings(raw if isinstance(raw, dict) else {})
        email_settings = _shared_pitcher_intel_email_settings()
        delivery_error = _pitching_recap_email_delivery_error(email_settings)
        effective_team_recipients = sanitized.get("team_recipients") or email_settings.get("team_recipients") or {}
        return {
            **sanitized,
            "league": _normalize_pitching_league(league),
            "team_recipients": effective_team_recipients,
            "email_provider": email_settings.get("email_provider"),
            "shared_email_configured": not bool(delivery_error),
            "has_resend_api_key": bool(str(email_settings.get("resend_api_key") or "").strip()),
            "has_smtp_password": bool(str(email_settings.get("smtp_password") or "").strip()),
            "smtp_from_name": str(email_settings.get("smtp_from_name") or ""),
            "smtp_from_email": str(email_settings.get("smtp_from_email") or ""),
        }

    def _get_pitching_recap_settings(*, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any]:
        raw = _modal_dict_get(
            pitching_recap_settings_store,
            _pitching_recap_settings_key(league=league),
            {},
        )
        return _sanitize_pitching_recap_settings(raw if isinstance(raw, dict) else {})

    def _save_pitching_recap_settings(
        patch: dict[str, Any] | None,
        *,
        league: str = DEFAULT_PITCHING_LEAGUE,
    ) -> dict[str, Any]:
        current = _get_pitching_recap_settings(league=league)
        merged = {**current, **(patch if isinstance(patch, dict) else {})}
        sanitized = _sanitize_pitching_recap_settings(merged)
        pitching_recap_settings_store.put(_pitching_recap_settings_key(league=league), sanitized)
        return sanitized

    def _send_recap_resend(html: str, text: str, subject: str, recipient: str, api_key: str) -> dict[str, Any]:
        if not api_key:
            return {"ok": False, "error": "No Resend API key configured"}
        payload = json.dumps(
            {
                "from": "The Brain <onboarding@resend.dev>",
                "to": [recipient],
                "subject": subject,
                "html": html,
                "text": text,
            }
        ).encode("utf-8")
        req = UrlRequest(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "the-brain/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=20) as resp:
                raw_body = resp.read()
                result = json.loads(raw_body) if raw_body else {}
                return {"ok": True, "id": result.get("id"), "response": result}
        except HTTPError as exc:
            raw_body = b""
            try:
                raw_body = exc.read()
            except Exception:
                raw_body = b""
            raw_text = raw_body.decode("utf-8", errors="replace").strip()
            parsed_body: Any = None
            if raw_text:
                try:
                    parsed_body = json.loads(raw_text)
                except Exception:
                    parsed_body = raw_text
            detail = ""
            if isinstance(parsed_body, dict):
                detail = str(parsed_body.get("message") or parsed_body.get("error") or parsed_body.get("name") or "").strip()
            elif isinstance(parsed_body, str):
                detail = parsed_body.strip()
            message = f"Resend {exc.code} {exc.reason}"
            if detail and detail.lower() not in message.lower():
                message += f" — {detail}"
            return {"ok": False, "error": message, "status_code": exc.code, "response": parsed_body}
        except URLError as exc:
            return {"ok": False, "error": f"Resend connection error: {exc.reason}"}
        except Exception as exc:
            return {"ok": False, "error": f"Resend error: {exc}"}

    def _send_recap_smtp(
        html: str,
        text: str,
        subject: str,
        recipient: str,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_name: str,
        from_email: str,
    ) -> dict[str, Any]:
        if not host or not username or not password or not from_email:
            return {"ok": False, "error": "SMTP is not fully configured"}

        import smtplib
        from email.message import EmailMessage
        from email.utils import formataddr

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((from_name or "brAIn", from_email))
        message["To"] = recipient
        message.set_content(text or "", subtype="plain", charset="utf-8")
        message.add_alternative(html or "", subtype="html", charset="utf-8")

        try:
            if int(port) == 465:
                with smtplib.SMTP_SSL(host, int(port), timeout=20) as server:
                    server.login(username, password)
                    server.send_message(message)
            else:
                with smtplib.SMTP(host, int(port), timeout=20) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(username, password)
                    server.send_message(message)
            return {"ok": True, "id": None, "response": {"provider": "smtp", "recipient": recipient}}
        except Exception as exc:
            return {"ok": False, "error": f"SMTP send failed: {exc}"}

    def _send_pitching_recap_email(
        html: str,
        text: str,
        subject: str,
        recipient: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        provider = _normalize_pitching_recap_email_provider((settings or {}).get("email_provider"))
        if provider == "smtp":
            return _send_recap_smtp(
                html,
                text,
                subject,
                recipient,
                host=str((settings or {}).get("smtp_host") or "").strip(),
                port=_smtp_port_value((settings or {}).get("smtp_port")),
                username=str((settings or {}).get("smtp_username") or "").strip(),
                password=str((settings or {}).get("smtp_password") or ""),
                from_name=str((settings or {}).get("smtp_from_name") or "brAIn").strip() or "brAIn",
                from_email=str((settings or {}).get("smtp_from_email") or "").strip(),
            )
        return _send_recap_resend(
            html,
            text,
            subject,
            recipient,
            str((settings or {}).get("resend_api_key") or "").strip(),
        )

    def _filter_pitching_recap_to_team(recap: dict[str, Any], team: str) -> dict[str, Any]:
        normalized_team = _normalize_pitching_recap_team(team)
        if not normalized_team:
            return dict(recap)
        filtered = dict(recap)
        starters = [
            dict(pitcher)
            for pitcher in (recap.get("starters") or [])
            if isinstance(pitcher, dict) and _normalize_pitching_recap_team(pitcher.get("team")) == normalized_team
        ]
        filtered["starters"] = starters
        return filtered

    def _pitching_recap_email_subject(recap: dict[str, Any], team: str) -> str:
        normalized_team = _normalize_pitching_recap_team(team) or str(team or "").upper()
        home_team = str(recap.get("home_team") or "")
        away_team = str(recap.get("away_team") or "")
        opponent = away_team if normalized_team == home_team else home_team
        game_date = str(recap.get("date") or "")
        opponent_label = f"vs {opponent}" if normalized_team == home_team else f"@ {opponent}"
        return f"brAIn Pitching Intelligence - {normalized_team} {opponent_label} - {game_date}"

    def _pitching_recap_email_html_v2(
        recap: dict[str, Any],
        team: str,
        replay_url: str | None = None,
        replay_payload: dict[str, Any] | None = None,
        preventable_lookup: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        normalized_team = _normalize_pitching_recap_team(team) or str(team or "").upper()
        home_team = str(recap.get("home_team") or "")
        away_team = str(recap.get("away_team") or "")
        final_home_score = recap.get("final_home_score")
        final_away_score = recap.get("final_away_score")
        pitchers = [dict(pitcher) for pitcher in (recap.get("starters") or []) if isinstance(pitcher, dict)]
        starters = [pitcher for pitcher in pitchers if str(pitcher.get("role") or "").lower() != "reliever"]
        relievers = [pitcher for pitcher in pitchers if str(pitcher.get("role") or "").lower() == "reliever"]
        opponent = away_team if normalized_team == home_team else home_team
        team_is_home = normalized_team == home_team
        opponent_label = f"vs {opponent}" if team_is_home else f"@ {opponent}"
        game_id = str(recap.get("game_id") or "")
        game_date = str(recap.get("date") or "")
        try:
            season = int(game_date[:4])
        except Exception:
            season = date.today().year
        official_linescore = _load_pitching_official_game_score(game_id, league=DEFAULT_PITCHING_LEAGUE) if game_id else {}
        if official_linescore.get("home_score") is not None:
            final_home_score = official_linescore.get("home_score")
        if official_linescore.get("away_score") is not None:
            final_away_score = official_linescore.get("away_score")
        team_score = final_home_score if team_is_home else final_away_score
        opponent_score = final_away_score if team_is_home else final_home_score
        final_score_line = f"{normalized_team} {team_score if team_score is not None else '-'} | {opponent} {opponent_score if opponent_score is not None else '-'}"
        _team_score_text = str(team_score) if team_score is not None else "-"
        _opp_score_text = str(opponent_score) if opponent_score is not None else "-"
        entries = [
            dict(entry)
            for entry in ((replay_payload or {}).get("entries") or [])
            if isinstance(entry, dict)
        ]
        entries_by_pitcher: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in entries:
            snapshot = entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {}
            pitcher_id = str(snapshot.get("pitcher_id") or "")
            if pitcher_id:
                entries_by_pitcher[pitcher_id].append(entry)

        def _safe(value: Any) -> str:
            return html.escape(str(value if value is not None else ""), quote=True)

        def _num(value: Any) -> float | None:
            try:
                if value in (None, ""):
                    return None
                number = float(value)
            except Exception:
                return None
            if math.isnan(number) or math.isinf(number):
                return None
            return number

        def _intish(value: Any) -> int | None:
            number = _num(value)
            return int(number) if number is not None else None

        def _clamp01(value: float | None) -> float:
            if value is None:
                return 0.0
            return max(0.0, min(1.0, float(value)))

        def _fmt_num(value: Any, digits: int = 1, fallback: str = "-") -> str:
            number = _num(value)
            if number is None:
                return fallback
            if digits <= 0:
                return f"{number:.0f}"
            return f"{number:.{digits}f}"

        def _fmt_signed(value: Any, digits: int = 2, fallback: str = "-") -> str:
            number = _num(value)
            if number is None:
                return fallback
            return f"{number:+.{digits}f}"

        def _fmt_pct(value: Any, fallback: str = "-") -> str:
            number = _num(value)
            if number is None:
                return fallback
            if abs(number) <= 1.0:
                number *= 100.0
            return f"{number:.0f}%"

        def _league_benchmark_context() -> dict[str, list[float]]:
            payload = _pitching_store_get(_pitching_preventable_model_latest_key(season=season))
            opportunities = payload.get("opportunities") if isinstance(payload, dict) and isinstance(payload.get("opportunities"), dict) else {}
            rows: list[dict[str, Any]] = []
            team_matrix = opportunities.get("teamGameMatrix") if isinstance(opportunities.get("teamGameMatrix"), dict) else {}
            for team_rows in team_matrix.values():
                if isinstance(team_rows, list):
                    rows.extend(dict(row) for row in team_rows if isinstance(row, dict))
            if not rows:
                for source_key in ("globalTop", "teamTop"):
                    source = opportunities.get(source_key)
                    if isinstance(source, list):
                        rows.extend(dict(row) for row in source if isinstance(row, dict))
                    elif isinstance(source, dict):
                        for team_rows in source.values():
                            if isinstance(team_rows, list):
                                rows.extend(dict(row) for row in team_rows if isinstance(row, dict))
            decision_values: list[float] = []
            exposure_values: list[float] = []
            for row in rows:
                decision = _num(row.get("decisionDelta") if row.get("decisionDelta") is not None else row.get("decision_delta"))
                exposure = _num(
                    row.get("projectedPreventableRuns")
                    if row.get("projectedPreventableRuns") is not None
                    else row.get("modelImpliedRunsSaved")
                    if row.get("modelImpliedRunsSaved") is not None
                    else row.get("projected_preventable_runs")
                )
                if decision is not None:
                    decision_values.append(decision)
                if exposure is not None:
                    exposure_values.append(exposure)
            return {"decision_delta": decision_values, "run_exposure": exposure_values}

        benchmark_context = _league_benchmark_context()

        def _benchmark_percentile(value: Any, values: list[float]) -> float | None:
            number = _num(value)
            clean_values = sorted(value for value in values if _num(value) is not None)
            if number is None or len(clean_values) < 20:
                return None
            below_or_equal = sum(1 for item in clean_values if item <= number)
            return below_or_equal / len(clean_values)

        def _benchmark_meter(value: Any, values: list[float], invert: bool = False) -> str:
            percentile = _benchmark_percentile(value, values)
            if percentile is None:
                return ""
            pct = max(2, min(98, int(round(percentile * 100))))
            top_pct = max(1, min(99, int(round((1.0 - percentile) * 100))))
            if percentile >= 0.66:
                color = "#f0d050" if invert else "#2ec4a0"
                label = f"Top {top_pct}%"
            elif percentile >= 0.33:
                color = "#f0d050"
                label = "Mid Range"
            else:
                bot_pct = max(1, min(99, int(round(percentile * 100))))
                color = "#2ec4a0" if invert else "#f0d050"
                label = f"Bottom {bot_pct}%"
            return (
                "<div style='margin-top:9px'>"
                "<div style='height:18px;position:relative;margin:0 4px'>"
                "<div style='position:absolute;left:0;right:0;top:8px;height:3px;background:#333333;border-radius:999px'></div>"
                "<div style='position:absolute;left:50%;top:4px;width:1px;height:11px;background:#7a7a7a;border-radius:2px'></div>"
                f"<div style='position:absolute;left:{pct}%;top:2px;width:13px;height:13px;margin-left:-6px;background:{color};border:2px solid #0a0a0a;border-radius:50%'></div>"
                "</div>"
                "<table style='width:100%;border-collapse:collapse;margin-top:2px'><tr>"
                "<td style='font-size:9px;color:#7a7a7a;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;text-align:left'>Low</td>"
                "<td style='font-size:9px;color:#7a7a7a;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;text-align:center'>Median</td>"
                "<td style='font-size:9px;color:#7a7a7a;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;text-align:right'>High</td>"
                "</tr></table>"
                "<table style='width:100%;border-collapse:collapse;margin-top:2px'><tr>"
                f"<td style='font-size:10px;color:{color};font-weight:800;letter-spacing:1px;text-align:center'>{_safe(label)} | {pct}th percentile</td>"
                "</tr></table>"
                "</div>"
            )

        _MLB_TEAM_PRIMARY: dict[str, str] = {
            "ARI": "#A71930", "AZ": "#A71930", "ARIZ": "#A71930",
            "ATL": "#CE1141", "BAL": "#DF4601", "BOS": "#BD3039",
            "CHC": "#0E3386", "CWS": "#C4CED4", "CHW": "#C4CED4", "CIN": "#C6011F",
            "CLE": "#E50022", "COL": "#33006F", "DET": "#FA4616", "HOU": "#EB6E1F",
            "KC": "#004687", "KCR": "#004687", "KAN": "#004687", "KANS": "#004687",
            "LAA": "#BA0021", "LAD": "#005A9C",
            "MIA": "#EF3340", "MIL": "#FFC52F", "MIN": "#D31145", "NYM": "#FF5910",
            "NYY": "#E4002C", "ATH": "#EFB21E", "OAK": "#EFB21E", "PHI": "#E81828",
            "PIT": "#FDB827", "SD": "#FFC425", "SDP": "#FFC425", "SF": "#FD5A1E",
            "SFG": "#FD5A1E", "SEA": "#005C5C", "STL": "#C41E3A",
            "TB": "#8FBCE6", "TBR": "#8FBCE6", "TAM": "#8FBCE6", "TAMP": "#8FBCE6",
            "TEX": "#C0111F", "TOR": "#134A8E", "WSH": "#AB0003", "WAS": "#AB0003",
        }

        def _team_primary_hex(team: Any) -> str:
            key = "".join(ch for ch in str(team or "").upper() if ch.isalpha())
            if not key:
                return "#2ec4a0"
            for length in range(len(key), 1, -1):
                candidate = key[:length]
                if candidate in _MLB_TEAM_PRIMARY:
                    return _MLB_TEAM_PRIMARY[candidate]
            return "#2ec4a0"

        def _hex_to_rgb(hex_value: str) -> tuple[int, int, int]:
            value = hex_value.lstrip("#")
            if len(value) != 6:
                return (46, 196, 160)
            return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))

        def _relative_luminance(hex_value: str) -> float:
            r, g, b = _hex_to_rgb(hex_value)
            def _channel(c: int) -> float:
                srgb = c / 255.0
                return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4
            return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)

        def _team_accents(team: Any) -> dict[str, str]:
            primary = _team_primary_hex(team)
            r, g, b = _hex_to_rgb(primary)
            luminance = _relative_luminance(primary)
            row_alpha = 0.10 if luminance >= 0.10 else 0.25
            label_color = primary if luminance >= 0.12 else "#ffffff"
            return {
                "primary": primary,
                "label": label_color,
                "dot": primary,
                "row_bg": f"rgba({r},{g},{b},{row_alpha:.2f})",
            }

        def _status_text(value: Any) -> str:
            return str(value or "STAY").replace("_", " ").title()

        def _person_name(value: Any) -> str:
            clean = str(value or "").strip()
            if not clean or "," not in clean:
                return clean
            last, first = [part.strip() for part in clean.split(",", 1)]
            return " ".join(part for part in (first, last) if part)

        def _state(entry: dict[str, Any] | None) -> dict[str, Any]:
            if not isinstance(entry, dict):
                return {}
            snapshot = entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {}
            state = snapshot.get("starter_state") if isinstance(snapshot.get("starter_state"), dict) else {}
            return state

        def _snapshot(entry: dict[str, Any] | None) -> dict[str, Any]:
            if not isinstance(entry, dict):
                return {}
            return entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {}

        def _entry_pitch_count(entry: dict[str, Any]) -> int | None:
            state = _state(entry)
            snapshot = _snapshot(entry)
            return _intish(
                state.get("official_pitch_count_in_game")
                or state.get("pitch_count_in_game")
                or snapshot.get("pitch_count")
            )

        def _pitcher_entries(pitcher: dict[str, Any]) -> list[dict[str, Any]]:
            return entries_by_pitcher.get(str(pitcher.get("pitcher_id") or ""), [])

        def _signal_entry(pitcher: dict[str, Any]) -> dict[str, Any] | None:
            pitcher_entries = _pitcher_entries(pitcher)
            if not pitcher_entries:
                return None
            target_pc = _intish(pitcher.get("first_pull_now_pitch_count") or pitcher.get("first_alert_pitch_count"))
            if target_pc is not None:
                exact = [entry for entry in pitcher_entries if _entry_pitch_count(entry) == target_pc]
                if exact:
                    return exact[0]
                nearby = [
                    entry
                    for entry in pitcher_entries
                    if _entry_pitch_count(entry) is not None
                    and abs(int(_entry_pitch_count(entry) or 0) - target_pc) <= 2
                ]
                if nearby:
                    nearby.sort(key=lambda entry: abs(int(_entry_pitch_count(entry) or 0) - target_pc))
                    return nearby[0]
            return pitcher_entries[-1]

        def _preventable_row(pitcher: dict[str, Any], entry: dict[str, Any] | None) -> dict[str, Any] | None:
            if not isinstance(preventable_lookup, dict):
                return None
            pitcher_id = str(pitcher.get("pitcher_id") or "")
            game_id = str(recap.get("game_id") or "")
            target_pc = _entry_pitch_count(entry or {}) or _intish(pitcher.get("first_pull_now_pitch_count") or pitcher.get("first_alert_pitch_count"))
            if game_id and pitcher_id and target_pc is not None:
                for offset in (0, -1, 1, -2, 2, -3, 3):
                    row = preventable_lookup.get(f"{game_id}:{pitcher_id}:{target_pc + offset}")
                    if isinstance(row, dict):
                        return row
            if game_id and pitcher_id:
                row = preventable_lookup.get(f"{game_id}:{pitcher_id}")
                if isinstance(row, dict):
                    return row
            return None

        def _mound_signal(pitcher: dict[str, Any]) -> dict[str, Any]:
            signal = pitcher.get("mound_signal")
            return dict(signal) if isinstance(signal, dict) else {}

        def _opportunity_value(row: dict[str, Any] | None) -> float | None:
            if not isinstance(row, dict):
                return None
            return _num(row.get("projectedPreventableRuns") if row.get("projectedPreventableRuns") is not None else row.get("modelImpliedRunsSaved"))

        def _decision_delta(pitcher: dict[str, Any], row: dict[str, Any] | None) -> float | None:
            signal = _mound_signal(pitcher)
            return (
                _num((row or {}).get("decisionDelta"))
                or _num(signal.get("decision_delta"))
                or _num(signal.get("decisionDelta"))
            )

        def _damage_risk(row: dict[str, Any] | None) -> float | None:
            if not isinstance(row, dict):
                return None
            return (
                _num(row.get("projectedDamageProbability"))
                or _num(row.get("damageProbability"))
                or _num(row.get("damage_probability"))
                or _num(row.get("calibrationMeanDamage"))
                or _num(row.get("calibration_mean_damage"))
            )

        def _recommended_reliever(pitcher: dict[str, Any], row: dict[str, Any] | None) -> str:
            signal = _mound_signal(pitcher)
            candidate = signal.get("top_candidate") if isinstance(signal.get("top_candidate"), dict) else {}
            return _person_name(
                (row or {}).get("recommendedRelieverName")
                or (row or {}).get("recommended_reliever_name")
                or candidate.get("player_name")
                or candidate.get("pitcher_name")
                or candidate.get("name")
                or "Relief option pending"
            )

        def _degradation_score(state: dict[str, Any], row: dict[str, Any] | None) -> float | None:
            return (
                _num(state.get("enhanced_degradation_score"))
                or _num(state.get("degradation_score"))
                or _num((row or {}).get("productionDegradation"))
                or _num((row or {}).get("normalizedDegradation"))
            )

        def _stuff_score(state: dict[str, Any], row: dict[str, Any] | None) -> int | None:
            score = _degradation_score(state, row)
            if score is None:
                return None
            return max(0, min(100, int(round(100.0 - score * 22.0))))

        def _pitch_type_label(value: Any) -> str:
            pitch_type = str(value or "").upper()
            labels = {
                "FF": "Four-Seam",
                "FA": "Fastball",
                "SI": "Sinker",
                "SL": "Slider",
                "ST": "Sweeper",
                "CH": "Changeup",
                "CU": "Curveball",
                "KC": "Knuckle Curve",
                "FC": "Cutter",
                "FS": "Splitter",
            }
            return labels.get(pitch_type, str(value or "Pitch"))

        def _pitch_mix_rows(pitcher: dict[str, Any]) -> str:
            pitcher_entries = _pitcher_entries(pitcher)
            if not pitcher_entries:
                return "<div style='padding:10px;color:#a0a0a0;font-size:12px'>Pitch mix unavailable in this replay artifact.</div>"
            groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "velo": []})
            for entry in pitcher_entries:
                snapshot = _snapshot(entry)
                pitch_type = _pitch_type_label(snapshot.get("pitch_type") or snapshot.get("pitch_name"))
                groups[pitch_type]["count"] += 1
                velo = _num(snapshot.get("release_speed") or snapshot.get("start_speed"))
                if velo is not None:
                    groups[pitch_type]["velo"].append(velo)
            total = sum(int(group["count"]) for group in groups.values())
            ranked = sorted(groups.items(), key=lambda item: int(item[1]["count"]), reverse=True)[:5]
            colors = ["#2ec4a0", "#4488ee", "#f0d050", "#d44f8a", "#4acfdc"]
            start = 0
            stops: list[str] = []
            legend: list[str] = []
            for label, group in ranked:
                count = int(group["count"])
                pct = round(count * 100 / total) if total else 0
                end = start + pct
                color = colors[len(stops) % len(colors)]
                stops.append(f"{color} {start}% {end}%")
                start = end
                velocities = group.get("velo") or []
                avg_velo = sum(velocities) / len(velocities) if velocities else None
                legend.append(
                    "<div style='margin-bottom:7px;color:#a0a0a0;font-size:12px;line-height:1.25'>"
                    f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;background:{color};margin-right:6px'></span>"
                    f"<strong style='color:#f0f0f0;font-weight:800'>{_safe(label)}</strong> <span style='color:{color};font-weight:800'>{pct}%</span>"
                    f"<span style='color:#7a7a7a'> · {_fmt_num(avg_velo, 1)} mph</span>"
                    "</div>"
                )
            return (
                "<table align='center' style='border-collapse:collapse;margin:12px auto 0'><tr>"
                "<td style='width:98px;vertical-align:middle'>"
                f"<div style='width:82px;height:82px;border-radius:50%;background:conic-gradient({', '.join(stops)});position:relative;border:1px solid #1e1e1e'>"
                "<div style='width:42px;height:42px;border-radius:50%;background:#0a0a0a;position:absolute;margin:20px'></div>"
                "</div></td>"
                f"<td style='vertical-align:middle;padding-left:14px'>{''.join(legend)}</td>"
                "</tr></table>"
            )

        def _base_state_label(value: Any) -> str:
            state = str(value or "").strip()
            if not state:
                return "base state unavailable"
            if state == "000":
                return "bases empty"
            occupied = {
                "first": len(state) >= 1 and state[0] == "1",
                "second": len(state) >= 2 and state[1] == "1",
                "third": len(state) >= 3 and state[2] == "1",
            }
            if all(occupied.values()):
                return "bases loaded"
            bases = [label for label, is_on in occupied.items() if is_on]
            if not bases:
                return "bases empty"
            if len(bases) == 1:
                return f"man on {bases[0]}"
            return "men on " + " and ".join([", ".join(bases[:-1]), bases[-1]] if len(bases) > 2 else bases)

        def _outs_phrase(value: Any) -> str:
            outs = _intish(value)
            if outs is None:
                return "outs unavailable"
            if outs == 0:
                return "no outs"
            if outs == 1:
                return "one out"
            return f"{outs} outs"

        def _inning_label(row: dict[str, Any] | None, pitcher: dict[str, Any]) -> str:
            inning = (row or {}).get("inning")
            half = str((row or {}).get("half") or "").strip().lower()
            if inning is None:
                inning = pitcher.get("first_pull_now_inning") or pitcher.get("first_alert_inning")
            if not inning:
                return "Inning unavailable"
            half_label = "Top" if half == "top" else "Bottom" if half == "bottom" else "Inning"
            return f"{half_label} {inning}"

        def _score_at_signal(row: dict[str, Any] | None, entry: dict[str, Any] | None, pitcher: dict[str, Any]) -> str:
            snapshot = _snapshot(entry)
            signal = _mound_signal(pitcher)
            current_away = (
                (row or {}).get("currentAwayScore")
                if (row or {}).get("currentAwayScore") is not None
                else (row or {}).get("current_away_score")
            )
            current_home = (
                (row or {}).get("currentHomeScore")
                if (row or {}).get("currentHomeScore") is not None
                else (row or {}).get("current_home_score")
            )
            if current_away is None:
                current_away = (
                    snapshot.get("away_score")
                    if snapshot.get("away_score") is not None
                    else signal.get("current_away_score")
                    if signal.get("current_away_score") is not None
                    else signal.get("currentAwayScore")
                )
            if current_home is None:
                current_home = (
                    snapshot.get("home_score")
                    if snapshot.get("home_score") is not None
                    else signal.get("current_home_score")
                    if signal.get("current_home_score") is not None
                    else signal.get("currentHomeScore")
                )
            if current_away is None or current_home is None:
                return "Score at signal not in source artifact"
            return f"{away_team} {current_away}, {home_team} {current_home}"

        def _entry_inning_label(entry: dict[str, Any] | None, fallback: Any = None) -> str:
            snapshot = _snapshot(entry)
            inning = _intish(snapshot.get("inning"))
            half = str(snapshot.get("half") or "").strip().lower()
            if inning is None and fallback not in (None, ""):
                fallback_text = str(fallback)
                if any(token in fallback_text.lower() for token in ("top", "bottom", "inning")):
                    return fallback_text
                inning = _intish(fallback)
            if inning is None:
                return "Inning unavailable"
            half_label = "Top" if half == "top" else "Bottom" if half == "bottom" else "Inning"
            return f"{half_label} {inning}"

        def _score_values(row: dict[str, Any] | None, entry: dict[str, Any] | None, pitcher: dict[str, Any] | None = None) -> tuple[Any, Any]:
            snapshot = _snapshot(entry)
            signal = _mound_signal(pitcher or {})
            away_score = (
                (row or {}).get("currentAwayScore")
                if (row or {}).get("currentAwayScore") is not None
                else (row or {}).get("current_away_score")
            )
            home_score = (
                (row or {}).get("currentHomeScore")
                if (row or {}).get("currentHomeScore") is not None
                else (row or {}).get("current_home_score")
            )
            if away_score is None:
                away_score = snapshot.get("away_score") if snapshot.get("away_score") is not None else signal.get("current_away_score") or signal.get("currentAwayScore")
            if home_score is None:
                home_score = snapshot.get("home_score") if snapshot.get("home_score") is not None else signal.get("current_home_score") or signal.get("currentHomeScore")
            return away_score, home_score

        def _score_html(away_score: Any, home_score: Any) -> str:
            if away_score is None or home_score is None:
                return "<span style='color:#7a7a7a'>Score unavailable</span>"
            away_color = "#ffffff" if normalized_team == away_team else "#7a7a7a"
            home_color = "#ffffff" if normalized_team == home_team else "#7a7a7a"
            away_weight = "800" if normalized_team == away_team else "400"
            home_weight = "800" if normalized_team == home_team else "400"
            return (
                f"<span style='color:{away_color};font-weight:{away_weight}'>{_safe(away_team)} {_safe(away_score)}</span>"
                "<span style='color:#7a7a7a;font-weight:400'> - </span>"
                f"<span style='color:{home_color};font-weight:{home_weight}'>{_safe(home_team)} {_safe(home_score)}</span>"
            )

        def _base_diamond(base_state: Any) -> str:
            state = str(base_state or "000").strip()
            state = (state + "000")[:3]

            def _base(on: bool, top: int, left: int) -> str:
                bg = "#e05b4b" if on else "#1a1a1a"
                border = "#e05b4b" if on else "rgba(255,255,255,0.1)"
                return (
                    f"<span style='position:absolute;top:{top}px;left:{left}px;width:11px;height:11px;"
                    f"background:{bg};border:1px solid {border};transform:rotate(45deg);display:block'></span>"
                )

            return (
                "<span style='display:inline-block;position:relative;width:42px;height:31px;vertical-align:middle' aria-label='bases'>"
                f"{_base(len(state) > 1 and state[1] == '1', 2, 15)}"
                f"{_base(len(state) > 0 and state[0] == '1', 15, 27)}"
                f"{_base(len(state) > 2 and state[2] == '1', 15, 3)}"
                "</span>"
            )

        def _outs_dots(outs: Any) -> str:
            count = max(0, min(3, _intish(outs) or 0))
            dots = []
            for index in range(3):
                filled = index < count
                bg = "#e05b4b" if filled else "#1a1a1a"
                border = "#e05b4b" if filled else "rgba(255,255,255,0.1)"
                dots.append(
                    f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;background:{bg};border:1px solid {border};margin-right:4px'></span>"
                )
            return "<span style='display:inline-block;vertical-align:middle'>" + "".join(dots) + "</span>"

        def _entry_base_state(entry: dict[str, Any] | None, row: dict[str, Any] | None = None) -> str:
            snapshot = _snapshot(entry)
            return str((row or {}).get("baseState") or snapshot.get("base_state") or "000")

        def _entry_outs(entry: dict[str, Any] | None, row: dict[str, Any] | None = None) -> int | None:
            snapshot = _snapshot(entry)
            return _intish((row or {}).get("outs") if (row or {}).get("outs") is not None else snapshot.get("outs"))

        def _actual_removal_entry(pitcher: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any] | None:
            pitcher_entries = _pitcher_entries(pitcher)
            if not pitcher_entries:
                return None
            target_pc = _intish((row or {}).get("actualChangePitchCount") or pitcher.get("actual_exit_pitch_count"))
            if target_pc is None:
                return pitcher_entries[-1] if ((row or {}).get("actualChangeInning") or pitcher.get("actual_exit_inning")) else None
            candidates = [entry for entry in pitcher_entries if _entry_pitch_count(entry) is not None]
            exact = [entry for entry in candidates if _entry_pitch_count(entry) == target_pc]
            if exact:
                return exact[-1]
            before = [entry for entry in candidates if int(_entry_pitch_count(entry) or 0) <= target_pc]
            if before:
                before.sort(key=lambda item: int(_entry_pitch_count(item) or 0))
                return before[-1]
            candidates.sort(key=lambda item: abs(int(_entry_pitch_count(item) or 0) - target_pc))
            return candidates[0] if candidates else None

        def _feature_label(value: Any) -> str:
            key = str(value or "").strip().lower()
            labels = {
                "base_traffic": "Traffic on base",
                "leverage_index": "Game leverage",
                "decision_delta": "Relief edge",
                "leveraged_production_degradation": "Degrading stuff in leverage",
                "production_degradation": "Starter degradation",
                "normalized_degradation": "Starter degradation",
                "starter_degradation": "Starter degradation",
                "starter_command_slip": "Command slipping",
                "starter_zone_miss": "Zone misses widening",
                "decay_velocity": "Velocity decay",
                "whiff_loss": "Whiff loss",
                "hard_contact_pressure": "Contact pressure",
            }
            return labels.get(key, key.replace("_", " ").title() if key else "Model factor")

        def _contributor_rows(row: dict[str, Any] | None, state: dict[str, Any], signal: dict[str, Any]) -> str:
            contributors = (row or {}).get("topFeatureContributions")
            if not isinstance(contributors, list) or not contributors:
                component_contributions = state.get("component_contributions") if isinstance(state.get("component_contributions"), dict) else {}
                if component_contributions:
                    contributors = [
                        {"feature": key, "contribution": value, "value": value}
                        for key, value in sorted(
                            component_contributions.items(),
                            key=lambda item: abs(_num(item[1]) or 0.0),
                            reverse=True,
                        )[:4]
                    ]
                else:
                    reasons = signal.get("top_reasons") if isinstance(signal.get("top_reasons"), list) else []
                    contributors = [{"feature": reason, "contribution": None, "value": "signal"} for reason in reasons[:4]]
            if not contributors:
                return "<div style='color:#a0a0a0;font-size:12px;line-height:1.45'>No ranked contributor detail was attached to this replay window.</div>"
            chips: list[str] = []
            for item in contributors[:4]:
                if not isinstance(item, dict):
                    continue
                pct = _num(item.get("percentile"))
                contribution = _num(item.get("contribution"))
                value = item.get("value")
                if isinstance(value, str) and value == "signal":
                    value_text = "signal reason"
                    headline = "active"
                else:
                    value_text = f"value {_fmt_num(value, 2)}"
                    headline = _fmt_pct(pct) if pct is not None else _fmt_signed(contribution, 2) if contribution is not None else "active"
                chips.append(
                    "<td style='padding:0 6px 6px 0;vertical-align:top'>"
                    "<div style='border:1px solid #1e1e1e;background:#1a1a1a;border-radius:8px;padding:9px 10px'>"
                    f"<div style='font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#7a7a7a;font-weight:700'>{_safe(_feature_label(item.get('feature')))}</div>"
                    f"<div style='margin-top:4px;color:#ffffff;font-size:14px;font-weight:800;letter-spacing:-0.3px'>{_safe(headline)}</div>"
                    f"<div style='margin-top:2px;color:#a0a0a0;font-size:11px'>{_safe(value_text)}</div>"
                    "</div></td>"
                )
            return "<table style='width:100%;border-collapse:collapse'><tr>" + "".join(chips) + "</tr></table>"

        def _factor_data(pitcher: dict[str, Any], entry: dict[str, Any] | None, row: dict[str, Any] | None) -> list[dict[str, Any]]:
            state = _state(entry)
            signal = _mound_signal(pitcher)
            def _state_num(*keys: str) -> float | None:
                for key in keys:
                    if key in state:
                        number = _num(state.get(key))
                        if number is not None:
                            return number
                return None

            strike_rate = _state_num("strike_rate_10")
            ball_rate = _state_num("ball_rate_10")
            if strike_rate is None and ball_rate is not None:
                strike_rate = 1.0 - float(ball_rate)
            called_strike_rate = _state_num("called_strike_rate_15", "called_strike_rate_10")
            chase_rate = _state_num("chase_rate_proxy_15", "chase_proxy_rate_15", "chase_rate_proxy_10", "chase_proxy_rate_10", "chase_rate_proxy")
            hard_contact = _state_num("hard_contact_rate_15", "hard_contact_rate_10")
            zone_miss = _state_num("zone_miss_distance_10", "zone_miss_distance_5")
            location_spread = _state_num("location_dispersion_10", "location_dispersion_5")
            pitch_mix_drift = _state_num("pitch_mix_drift_10", "pitch_mix_drift")
            whiff_rate = _state_num("whiff_rate_15")
            whiff_drop = _state_num("opponent_adjusted_whiff_drop")
            velo_current = _state_num("velo_mean_10", "velo_mean_5")
            velo_baseline = _state_num("seasonal_velo_baseline", "calibrated_velo")
            velo_drop = _state_num("velo_drop", "velocity_drop")
            if velo_drop is None and velo_current is not None and velo_baseline is not None:
                velo_drop = velo_baseline - velo_current
            spin_current = _state_num("spin_mean_10", "spin_mean_5")
            spin_baseline = _state_num("seasonal_spin_baseline", "calibrated_spin")
            spin_drop = spin_baseline - spin_current if spin_current is not None and spin_baseline is not None else None
            inning_decay = _state_num("inning_decay_factor")
            tto_decay = _state_num("tto_decay_factor")
            tto = _state_num("times_through_order") or _num((row or {}).get("timesThroughOrder"))
            leverage = _num((row or {}).get("leverageIndex") or state.get("leverage_index") or signal.get("leverage_index"))
            base_state = str((row or {}).get("baseState") or "")
            base_pressure = sum(1 for char in base_state[:3] if char == "1") / 3.0 if base_state else 0.0
            decision = _decision_delta(pitcher, row)
            normalized_degradation = _state_num("normalized_degradation_score") or _num((row or {}).get("normalizedDegradation"))
            enhanced_degradation = _state_num("enhanced_degradation_score", "degradation_score") or _num((row or {}).get("productionDegradation"))
            league_percentile = _num(
                state.get("empirical_degradation_percentile")
                or state.get("league_percentile")
                or (row or {}).get("leaguePercentile")
            )
            pitcher_percentile = _num(
                state.get("pitcher_empirical_percentile")
                or state.get("pitcher_empirical_degradation_percentile")
                or state.get("pitcher_history_percentile")
                or (row or {}).get("pitcherHistoryPercentile")
            )

            command_pressure = max(
                _clamp01((zone_miss or 0.0) / 0.75),
                _clamp01((location_spread or 0.0) / 1.00),
                _clamp01(((1.0 - strike_rate) if strike_rate is not None else 0.0) / 0.45),
            )
            whiff_pressure = max(
                _clamp01((0.16 - (whiff_rate or 0.16)) / 0.16),
                _clamp01((whiff_drop or 0.0) / 0.20),
            )
            velocity_pressure = _clamp01(abs(velo_drop or 0.0) / 3.5)
            spin_pressure = _clamp01(abs(spin_drop or 0.0) / 350.0)
            pitch_mix_pressure = _clamp01(abs(pitch_mix_drift or 0.0) / 0.35)
            called_strike_pressure = _clamp01((0.14 - (called_strike_rate or 0.14)) / 0.14)
            chase_pressure = _clamp01((0.22 - (chase_rate or 0.22)) / 0.22)
            hard_contact_pressure = _clamp01((hard_contact or 0.0) / 0.42)
            fatigue_pressure = max(_clamp01(((inning_decay or 0.0) + (tto_decay or 0.0)) / 1.5), 0.70 if (tto or 0.0) >= 3 else 0.0)
            context_pressure = max(_clamp01((leverage or 0.0) / 2.2), base_pressure)
            relief_pressure = _clamp01(abs(decision or 0.0) / 4.0)
            normalized_pressure = _clamp01(normalized_degradation)
            enhanced_pressure = _clamp01((enhanced_degradation or 0.0) / 2.5)
            league_pressure = _clamp01(league_percentile / 100.0 if league_percentile and league_percentile > 1 else league_percentile)
            pitcher_history_pressure = _clamp01(pitcher_percentile / 100.0 if pitcher_percentile and pitcher_percentile > 1 else pitcher_percentile)

            factors = [
                {
                    "label": "Fastball Velocity",
                    "group": "Signal Rationale",
                    "score": velocity_pressure,
                    "value": f"{_fmt_num(velo_current, 1)} mph",
                    "detail": f"Baseline {_fmt_num(velo_baseline, 1)} mph; trend {_fmt_signed(-(velo_drop or 0.0), 1)} mph.",
                },
                {
                    "label": "Fastball Spin",
                    "group": "Signal Rationale",
                    "score": spin_pressure,
                    "value": f"{_fmt_num(spin_current, 0)} rpm",
                    "detail": f"Baseline {_fmt_num(spin_baseline, 0)} rpm; trend {_fmt_signed(-(spin_drop or 0.0), 0)} rpm.",
                },
                {
                    "label": "Swinging-Strike Rate",
                    "group": "Signal Rationale",
                    "score": whiff_pressure,
                    "value": _fmt_pct(whiff_rate),
                    "detail": f"Recent whiff rate; opponent-adjusted change {_fmt_signed(whiff_drop, 2)}.",
                },
                {
                    "label": "Pitch Mix Drift",
                    "group": "Signal Rationale",
                    "score": pitch_mix_pressure,
                    "value": _fmt_num(pitch_mix_drift, 2),
                    "detail": "Recent pitch selection movement from expected mix.",
                },
                {
                    "label": "Zone Control",
                    "group": "Command and Contact",
                    "score": command_pressure,
                    "value": _fmt_pct(strike_rate),
                    "detail": f"Strike rate {_fmt_pct(strike_rate)}; zone miss {_fmt_num(zone_miss, 2)} ft.",
                },
                {
                    "label": "Called-Strike Rate",
                    "group": "Command and Contact",
                    "score": called_strike_pressure,
                    "value": _fmt_pct(called_strike_rate),
                    "detail": "Called strikes over the recent command window.",
                },
                {
                    "label": "Chase Rate Proxy",
                    "group": "Command and Contact",
                    "score": chase_pressure,
                    "value": _fmt_pct(chase_rate),
                    "detail": "Hitters expanding against him.",
                },
                {
                    "label": "Hard Contact",
                    "group": "Command and Contact",
                    "score": hard_contact_pressure,
                    "value": _fmt_pct(hard_contact),
                    "detail": "Recent contact-quality pressure.",
                },
                {
                    "label": "Zone Miss",
                    "group": "Command and Contact",
                    "score": _clamp01((zone_miss or 0.0) / 0.75),
                    "value": f"{_fmt_num(zone_miss, 2)} ft",
                    "detail": "Average miss distance in the recent window.",
                },
                {
                    "label": "Command Spread",
                    "group": "Command and Contact",
                    "score": _clamp01((location_spread or 0.0) / 1.00),
                    "value": _fmt_num(location_spread, 2),
                    "detail": "Recent location spread.",
                },
                {
                    "label": "Game Leverage",
                    "group": "Decision Context",
                    "score": context_pressure,
                    "value": f"LI {_fmt_num(leverage, 2)}",
                    "detail": f"{_base_state_label(base_state)}; {_outs_phrase((row or {}).get('outs'))}; leverage {_fmt_num(leverage, 2)}.",
                },
                {
                    "label": "Normalized Degradation",
                    "group": "Decision Context",
                    "score": normalized_pressure,
                    "value": _fmt_pct(normalized_degradation),
                    "detail": "Normalized against comparable MLB windows.",
                },
                {
                    "label": "Enhanced Degradation",
                    "group": "Decision Context",
                    "score": enhanced_pressure,
                    "value": _fmt_num(enhanced_degradation, 2),
                    "detail": "Weighted model read after feature normalization.",
                },
                {
                    "label": "League Percentile",
                    "group": "Decision Context",
                    "score": league_pressure,
                    "value": _fmt_pct(league_percentile),
                    "detail": "Where this window ranks against comparable league windows.",
                },
                {
                    "label": "Pitcher History Percentile",
                    "group": "Decision Context",
                    "score": pitcher_history_pressure,
                    "value": _fmt_pct(pitcher_percentile),
                    "detail": "Where this window ranks against this pitcher's own history.",
                },
                {
                    "label": "Decay Pressure",
                    "group": "Decision Context",
                    "score": fatigue_pressure,
                    "value": f"{_fmt_num(inning_decay, 2)} inning | {_fmt_num(tto_decay, 2)} TTO",
                    "detail": f"{_fmt_num(tto, 0)} times through order.",
                },
                {
                    "label": "Relief Edge",
                    "group": "Decision Context",
                    "score": relief_pressure,
                    "value": _fmt_signed(decision, 2),
                    "detail": f"{_recommended_reliever(pitcher, row)} gave the model a better next-window path.",
                },
            ]
            visible = [factor for factor in factors if str(factor.get("value") or "-") != "-"]
            ranked = sorted(visible, key=lambda item: _clamp01(_num(item.get("score")) or 0.0), reverse=True)
            driver_ids = {id(factor) for factor in ranked[:4] if _clamp01(_num(factor.get("score")) or 0.0) >= 0.35}
            for factor in factors:
                score = _clamp01(_num(factor.get("score")) or 0.0)
                if id(factor) in driver_ids or score >= 0.70:
                    factor["role"] = "Driver"
                elif score <= 0.22 and str(factor.get("value") or "-") != "-":
                    factor["role"] = "Held Up"
                else:
                    factor["role"] = "Watch"
            return factors

        def _factor_bar(factor: dict[str, Any]) -> str:
            pct = int(round(_clamp01(_num(factor.get("score")) or 0.0) * 100))
            color = "#a33a35" if pct >= 70 else "#c6a64b" if pct >= 40 else "#3f7c68"
            return (
                "<tr>"
                f"<td style='padding:8px 10px 8px 0;width:150px;vertical-align:top;color:#0f172a;font-weight:800;font-size:12px'>{_safe(factor.get('label'))}</td>"
                "<td style='padding:8px 10px 8px 0;vertical-align:top'>"
                "<div style='height:9px;background:#e8e2d2;border-radius:999px;overflow:hidden'>"
                f"<div style='height:9px;width:{pct}%;background:{color};border-radius:999px'></div>"
                "</div>"
                f"<div style='margin-top:5px;color:#64748b;font-size:11px;line-height:1.35'>{_safe(factor.get('detail'))}</div>"
                "</td>"
                f"<td style='padding:8px 0;width:72px;vertical-align:top;text-align:right;color:{color};font-weight:900;font-size:12px'>{_safe(factor.get('value'))}</td>"
                "</tr>"
            )

        def _reason_phrase(value: Any) -> str:
            key = str(value or "").strip().upper()
            labels = {
                "STARTER_DEGRADATION": "starter condition was sliding",
                "DEG_LI_THRESHOLD": "degradation crossed the leverage threshold",
                "STARTER_VELO_DROP": "velocity trend added concern",
                "STARTER_COMMAND_SLIP": "command was slipping",
                "THIRD_TIME_THROUGH_ORDER": "lineup was seeing him for the third time",
                "RELIEVER_MATCHUP_EDGE": "the relief matchup was better",
                "RELIEVER_CONTRAST_EDGE": "the bullpen offered a different look",
                "HIGH_LEVERAGE_SPOT": "game pressure was elevated",
                "LEFTY_CLUSTER_AHEAD": "left-handed pocket was approaching",
            }
            return labels.get(key, str(value or "").replace("_", " ").lower())

        def _driver_card(factor: dict[str, Any]) -> str:
            pct = int(round(_clamp01(_num(factor.get("score")) or 0.0) * 100))
            role = str(factor.get("role") or "Watch")
            color = "#e05b4b" if role == "Driver" else "#2ec4a0" if role == "Held Up" else "#f0d050"
            label = str(factor.get("label") or "Signal driver")
            return (
                "<td style='width:33.333%;padding:0 8px 8px 0;vertical-align:top'>"
                "<div style='min-height:180px;background:#1a1a1a;border:1px solid #1e1e1e;border-radius:8px;padding:14px;box-sizing:border-box'>"
                "<table style='width:100%;border-collapse:collapse'><tr>"
                f"<td style='font-size:11px;letter-spacing:1.5px;text-transform:uppercase;line-height:1.3;color:#a0a0a0;font-weight:700'>{_safe(label)}</td>"
                f"<td style='width:62px;text-align:right;vertical-align:top;color:{color};font-weight:800;letter-spacing:1px;text-transform:uppercase;font-size:10px'>{_safe(role)}</td>"
                "</tr></table>"
                f"<div style='margin-top:12px;color:#ffffff;font-size:22px;line-height:1;font-weight:800;letter-spacing:-0.7px'>{_safe(factor.get('value'))}</div>"
                "<div style='height:3px;background:#333333;border-radius:999px;overflow:hidden;margin-top:12px'>"
                f"<div style='height:3px;width:{pct}%;background:{color};border-radius:999px'></div>"
                "</div>"
                f"<div style='margin-top:10px;color:#a0a0a0;font-size:12px;line-height:1.45'>{_safe(factor.get('detail'))}</div>"
                "</div></td>"
            )

        def _driver_panel(
            factors: list[dict[str, Any]],
            signal: dict[str, Any],
            pitcher: dict[str, Any] | None = None,
            entry: dict[str, Any] | None = None,
            row: dict[str, Any] | None = None,
        ) -> str:
            group_display = {
                "Signal Rationale": "Stuff & Movement",
                "Command and Contact": "Command and Contact",
                "Decision Context": "Decision Context",
            }
            groups = [
                ("Signal Rationale", [factor for factor in factors if factor.get("group") == "Signal Rationale"][:6]),
                ("Command and Contact", [factor for factor in factors if factor.get("group") == "Command and Contact"][:6]),
                ("Decision Context", [factor for factor in factors if factor.get("group") == "Decision Context"][:6]),
            ]
            sections: list[str] = []
            for group_key, group_factors in groups:
                if not group_factors:
                    continue
                display_title = group_display.get(group_key, group_key)
                rows = []
                for index in range(0, len(group_factors), 3):
                    chunk = group_factors[index:index + 3]
                    while len(chunk) < 3:
                        chunk.append(None)
                    rows.append(
                        "<tr>" + "".join(
                            _driver_card(factor) if factor else "<td style='width:33.333%;padding:0 8px 8px 0'></td>"
                            for factor in chunk
                        ) + "</tr>"
                    )
                sections.append(
                    "<div style='margin-top:16px'>"
                    f"<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a0a0a0;font-weight:700'>{_safe(display_title)}</div>"
                    f"<table style='width:100%;border-collapse:collapse;margin-top:10px;table-layout:fixed'>{''.join(rows)}</table>"
                    "</div>"
                )

            trend_mix_row = ""
            if pitcher is not None:
                pitch_mix_card = (
                    "<div style='min-height:280px;background:#1a1a1a;border:1px solid #1e1e1e;border-radius:8px;padding:14px;box-sizing:border-box'>"
                    "<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a0a0a0;font-weight:700'>Pitch Mix Snapshot</div>"
                    f"{_pitch_mix_rows(pitcher)}"
                    "</div>"
                )
                trend_mix_row = (
                    "<div style='margin-top:16px'>"
                    "<table style='width:100%;border-collapse:collapse;table-layout:fixed'><tr>"
                    "<td style='width:50%;padding:0 8px 0 0;vertical-align:top'>"
                    f"{_stuff_trend_panel(pitcher, entry, row)}"
                    "</td>"
                    "<td style='width:50%;padding:0 0 0 8px;vertical-align:top'>"
                    f"{pitch_mix_card}"
                    "</td>"
                    "</tr></table>"
                    "</div>"
                )

            tooltip_text = "Feature meters show degradation pressure. Higher pressure means the feature was more concerning or more signal-driving; green boxes are counter-signals that held up."
            return (
                "<div style='border:1px solid #1e1e1e;background:#0a0a0a;border-radius:8px;padding:18px 18px 14px;margin-top:18px'>"
                "<div style='font-size:18px;line-height:1.1;font-weight:800;letter-spacing:-0.5px;color:#ffffff'>"
                "<span style='display:inline-block;width:7px;height:7px;border-radius:50%;background:#2ec4a0;margin-right:8px;vertical-align:middle'></span>"
                "Signal Rationale"
                f"<span title='{_safe(tooltip_text)}' style='display:inline-block;margin-left:8px;width:16px;height:16px;border-radius:50%;border:1px solid #333333;color:#a0a0a0;font-size:11px;font-weight:700;text-align:center;line-height:14px;vertical-align:middle;cursor:help'>i</span>"
                "</div>"
                f"{''.join(sections)}"
                f"{trend_mix_row}"
                "</div>"
            )

        def _held_up_text(factors: list[dict[str, Any]]) -> str:
            held = [factor for factor in factors if _clamp01(_num(factor.get("score")) or 0.0) <= 0.28 and str(factor.get("value") or "-") != "-"]
            if not held:
                return "No clean counter-signal stood out strongly enough to offset the decision edge."
            labels = [f"{factor['label']} held ({factor['value']})" for factor in held[:3]]
            return "; ".join(labels) + "."

        def _stuff_trend_panel(pitcher: dict[str, Any], entry: dict[str, Any] | None, row: dict[str, Any] | None) -> str:
            by_inning: dict[int, tuple[int, int]] = {}
            for item in _pitcher_entries(pitcher):
                snapshot = _snapshot(item)
                inning = _intish(snapshot.get("inning"))
                score = _stuff_score(_state(item), None)
                pc = _entry_pitch_count(item) or 0
                if inning is not None and score is not None:
                    previous = by_inning.get(inning)
                    if previous is None or pc >= previous[0]:
                        by_inning[inning] = (pc, score)
            inning_scores = [
                (inning, score)
                for inning, (_pc, score) in sorted(by_inning.items())
            ]
            game_score = (
                sum(score for _, score in inning_scores) / len(inning_scores)
                if inning_scores
                else None
            )
            peak_score = _stuff_score(_state(entry), row)
            peak_inning = _intish(_snapshot(entry).get("inning")) if entry else None
            if not inning_scores and peak_score is None:
                return (
                    "<div style='min-height:280px;background:#1a1a1a;border:1px solid #1e1e1e;border-radius:8px;padding:14px;box-sizing:border-box'>"
                    "<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a0a0a0;font-weight:700'>Stuff Score Trend</div>"
                    "<div style='margin-top:7px;color:#a0a0a0;font-size:12px;line-height:1.45'>Stuff score detail was not attached to this replay artifact.</div>"
                    "</div>"
                )
            trend_points = inning_scores[:9]
            if len(trend_points) == 1:
                polyline = "8,34 212,34"
                point_coords = [(8.0, 34.0, trend_points[0][0], trend_points[0][1])]
            else:
                min_score = min(score for _, score in trend_points)
                max_score = max(score for _, score in trend_points)
                span = max(1.0, max_score - min_score)
                coords = []
                point_coords = []
                for index, (_inning, score) in enumerate(trend_points):
                    x = 8 + index * (204 / max(1, len(trend_points) - 1))
                    y = 58 - ((score - min_score) / span) * 44
                    coords.append(f"{x:.1f},{y:.1f}")
                    point_coords.append((x, y, _inning, score))
                polyline = " ".join(coords)
            circles = "".join(
                f"<circle cx='{x:.1f}' cy='{y:.1f}' r='3.5' fill='{'#f0d050' if peak_inning == inning else '#f0f0f0'}'/>"
                for x, y, inning, _score in point_coords
            )
            value_labels = "".join(
                f"<text x='{x:.1f}' y='{max(9.0, y - 7):.1f}' text-anchor='middle' fill='{'#f0d050' if peak_inning == inning else '#a0a0a0'}' font-size='9' font-weight='700'>{score:.0f}</text>"
                for x, y, inning, score in point_coords
            )
            inning_labels = "".join(
                f"<text x='{x:.1f}' y='80' text-anchor='middle' fill='{'#f0d050' if peak_inning == inning else '#7a7a7a'}' font-size='9' font-weight='700' letter-spacing='1'>I{inning}</text>"
                for x, y, inning, _score in point_coords
            )
            return (
                "<div style='min-height:280px;background:#1a1a1a;border:1px solid #1e1e1e;border-radius:8px;padding:14px;box-sizing:border-box'>"
                "<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a0a0a0;font-weight:700'>Stuff Score Trend</div>"
                "<table style='width:100%;border-collapse:collapse;margin-top:10px'><tr>"
                "<td style='vertical-align:top;width:50%'>"
                f"<div style='font-size:22px;line-height:1;color:#ffffff;font-weight:800;letter-spacing:-1px'>{_safe(_fmt_num(game_score, 0))}</div>"
                "<div style='margin-top:6px;color:#a0a0a0;font-size:11px;line-height:1.4'>Game Stuff Score<br>inning-window average</div>"
                "</td>"
                "<td style='vertical-align:top;width:50%'>"
                f"<div style='font-size:22px;line-height:1;color:#f0d050;font-weight:800;letter-spacing:-1px'>{_safe(_fmt_num(peak_score, 0))}</div>"
                "<div style='margin-top:6px;color:#a0a0a0;font-size:11px;line-height:1.4'>Peak Window Stuff Score<br>at model signal</div>"
                "</td></tr></table>"
                "<div style='margin-top:12px;background:#0a0a0a;border:1px solid #1e1e1e;border-radius:8px;padding:7px'>"
                "<svg width='100%' height='88' viewBox='0 0 220 88' role='img' aria-label='Stuff Score trend line' style='display:block'>"
                "<line x1='8' y1='58' x2='212' y2='58' stroke='#333333' stroke-width='1'/>"
                "<line x1='8' y1='14' x2='212' y2='14' stroke='#333333' stroke-width='1'/>"
                f"<polyline points='{_safe(polyline)}' fill='none' stroke='#f0f0f0' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>"
                f"{circles}"
                f"{value_labels}"
                f"{inning_labels}"
                "</svg>"
                "</div>"
                "</div>"
            )

        def _gm_rationale_text(
            pitcher: dict[str, Any],
            factors: list[dict[str, Any]],
            recommended: str,
            decision: float | None,
            exposure: float | None,
            damage: float | None,
        ) -> str:
            starter_name = _person_name(pitcher.get("pitcher_name") or "the starter")
            ranked = sorted(factors, key=lambda item: _clamp01(_num(item.get("score")) or 0.0), reverse=True)
            phrase_map = {
                "Fastball Velocity": "velocity was trending down",
                "Fastball Spin": "fastball spin was no longer providing the same cushion",
                "Swinging-Strike Rate": "he was getting fewer swing-and-miss finishes",
                "Pitch Mix Drift": "his pitch mix had moved away from its normal shape",
                "Zone Control": "command was slipping",
                "Called-Strike Rate": "called strikes were harder to steal",
                "Chase Rate Proxy": "hitters were chasing less often",
                "Hard Contact": "contact quality was becoming more dangerous",
                "Zone Miss": "misses were spreading farther from the zone",
                "Command Spread": "location spread had widened",
                "Game Leverage": "the game state made the next hitter pocket more expensive",
                "Normalized Degradation": "the window graded poorly against comparable MLB starter windows",
                "Enhanced Degradation": "the combined starter-read moved into a danger range",
                "League Percentile": "the signal ranked high against comparable league windows",
                "Pitcher History Percentile": "the signal was elevated against this pitcher's own history",
                "Decay Pressure": "inning and times-through-order pressure were adding up",
                "Relief Edge": "a better relief path was available",
            }

            def _join_phrases(items: list[str]) -> str:
                if not items:
                    return ""
                if len(items) == 1:
                    return items[0]
                if len(items) == 2:
                    return f"{items[0]} and {items[1]}"
                return ", ".join(items[:-1]) + f", and {items[-1]}"

            changed = [
                phrase_map.get(str(item.get("label") or ""), str(item.get("label") or "").lower())
                for item in ranked
                if item.get("role") == "Driver" and item.get("label")
            ]
            if not changed:
                changed = [
                    phrase_map.get(str(item.get("label") or ""), str(item.get("label") or "").lower())
                    for item in ranked[:3]
                    if item.get("label")
                ]
            context_factor = next((item for item in factors if item.get("label") == "Game Leverage"), None)
            context_text = str(context_factor.get("detail") or "Game context added urgency.") if isinstance(context_factor, dict) else "Game context added urgency."
            held = [
                phrase_map.get(str(item.get("label") or ""), str(item.get("label") or "").lower())
                for item in factors
                if item.get("role") == "Held Up"
            ]
            held_text = _join_phrases(held[:3]) if held else "no clean counter-signal fully offset the recommendation"
            relief_text = (
                f"{recommended} projected {_fmt_signed(decision, 2)} fewer runs than asking {starter_name} to face the next pocket."
                if decision is not None and recommended and "pending" not in recommended.lower()
                else "The model compared the starter against the best available relief path, but the named option was not resolved in this artifact."
            )
            exposure_text = (
                f"The window carried {_fmt_num(exposure, 2)} runs of calibrated exposure"
                if exposure is not None
                else "The model did not attach a calibrated run-exposure value"
            )
            damage_text = f" and a {_fmt_pct(damage)} comparable-window damage risk." if damage is not None else "."
            bullets = [
                f"{starter_name}'s signal moved because {_join_phrases(changed[:3]) or 'the late-window indicators were moving in the wrong direction'}.",
                f"At the signal, the context was {context_text}",
                f"The model preferred the relief path because {relief_text}",
                f"This was a real run-prevention spot: {exposure_text}{damage_text}",
                f"The main counter-signal was that {held_text}.",
            ]
            return (
                "<div style='margin-top:14px;padding:14px 16px;background:#0a0a0a;border:1px solid #1e1e1e;border-radius:8px;color:#a0a0a0'>"
                "<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#2ec4a0;font-weight:700'>Key Insights</div>"
                "<ul style='margin:10px 0 0 18px;padding:0;color:#a0a0a0;font-size:13px;line-height:1.55'>"
                + "".join(f"<li style='margin-bottom:5px'>{_safe(bullet)}</li>" for bullet in bullets)
                + "</ul></div>"
            )

        def _metric_tiles(metrics: list[tuple[str, str, str] | tuple[str, str, str, str]]) -> str:
            if not metrics:
                return ""
            width = max(1, int(100 / len(metrics)))
            cells = []
            for metric in metrics:
                label, value, detail = metric[:3]
                benchmark_html = metric[3] if len(metric) > 3 else ""
                cells.append(_metric_tile(label, value, detail, width_pct=width, benchmark_html=benchmark_html))
            return "<table style='width:100%;border-collapse:collapse;table-layout:fixed'><tr>" + "".join(cells) + "</tr></table>"

        def _metric_tile(label: str, value: str, detail: str = "", width_pct: int = 25, benchmark_html: str = "", value_color: str = "#2ec4a0") -> str:
            return (
                f"<td style='width:{width_pct}%;padding:0 8px 8px 0;vertical-align:top'>"
                "<div style='min-height:220px;background:#1a1a1a;border:1px solid #1e1e1e;border-radius:8px;padding:14px;box-sizing:border-box'>"
                f"<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a0a0a0;font-weight:700'>{_safe(label)}</div>"
                f"<div style='margin-top:10px;color:{value_color};font-size:32px;line-height:1;font-weight:800;letter-spacing:-1.5px'>{_safe(value)}</div>"
                f"{benchmark_html}"
                f"<div style='margin-top:9px;color:#a0a0a0;font-size:11px;line-height:1.4'>{_safe(detail)}</div>"
                "</div></td>"
            )

        def _box_value(value: Any) -> str:
            return str(value if value not in (None, "") else "-")

        def _pitcher_sort_key(index_and_pitcher: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
            index, pitcher = index_and_pitcher
            box = pitcher.get("boxscore") if isinstance(pitcher.get("boxscore"), dict) else {}
            signal = pitcher.get("bullpen_signal") if isinstance(pitcher.get("bullpen_signal"), dict) else {}
            order = _intish(
                box.get("appearance_order")
                or pitcher.get("appearance_order")
                or pitcher.get("teamAppearanceOrder")
                or pitcher.get("team_appearance_order")
            )
            entry_inning = _intish(
                pitcher.get("entry_inning")
                or pitcher.get("entryInning")
                or signal.get("trigger_inning")
                or pitcher.get("first_alert_inning")
            )
            entry_pitch_count = _intish(
                pitcher.get("entry_pitch_count")
                or pitcher.get("entryPitchCount")
                or signal.get("trigger_pitch_count")
                or pitcher.get("first_alert_pitch_count")
            )
            return (order if order is not None else 999, entry_inning if entry_inning is not None else 999, entry_pitch_count if entry_pitch_count is not None else 999, index)

        def _ordered_pitchers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [pitcher for _index, pitcher in sorted(enumerate(rows), key=_pitcher_sort_key)]

        def _pitcher_line(pitcher: dict[str, Any]) -> str:
            box = pitcher.get("boxscore") if isinstance(pitcher.get("boxscore"), dict) else {}
            return (
                f"{_box_value(box.get('ip') or pitcher.get('innings_pitched'))} IP, "
                f"{_box_value(box.get('h') if box else pitcher.get('hits_allowed'))} H, "
                f"{_box_value(box.get('r') if box else pitcher.get('runs_allowed_total'))} R, "
                f"{_box_value(box.get('er') if box else pitcher.get('earned_runs_total'))} ER, "
                f"{_box_value(box.get('bb') if box else pitcher.get('walks'))} BB, "
                f"{_box_value(box.get('so') if box else pitcher.get('strikeouts'))} K"
            )

        def _game_boxscore_section() -> str:
            def _rss_read(pitcher: dict[str, Any]) -> str:
                signal = pitcher.get("bullpen_signal") if isinstance(pitcher.get("bullpen_signal"), dict) else {}
                component_keys = {
                    "Command": ("rss_command", "command_score", "commandStress", "command_stress"),
                    "Result": ("rss_outcome", "outcome_score", "outcomeStress", "outcome_stress"),
                    "Workload": ("rss_usage_fatigue", "rss_workload", "workload_score", "workloadStress"),
                    "Handoff": ("rss_handoff_risk", "handoff_score", "handoffStress", "handoff_risk"),
                    "Stuff": ("rss_stuff", "stuff_score", "stuffStress", "stuff_stress"),
                }
                components: list[tuple[str, float]] = []
                for label, keys in component_keys.items():
                    value = next((_num(signal.get(key)) for key in keys if _num(signal.get(key)) is not None), None)
                    if value is not None:
                        components.append((label, value))
                if components:
                    components.sort(key=lambda item: item[1], reverse=True)
                    return components[0][0]
                summary = str(signal.get("summary") or "").lower()
                if "command" in summary:
                    return "Command"
                if "workload" in summary or "fatigue" in summary:
                    return "Workload"
                if "handoff" in summary:
                    return "Handoff"
                if "stuff" in summary:
                    return "Stuff"
                if "outcome" in summary or "result" in summary or "run" in summary:
                    return "Result"
                return "Unavailable"

            innings = [inning for inning in (official_linescore.get("innings") or []) if isinstance(inning, dict)]
            if not innings:
                max_inning = 9
                innings = [{"num": index, "away": None, "home": None} for index in range(1, max_inning + 1)]

            def _rss_color(label_text: str) -> str:
                lowered = (label_text or "").strip().lower()
                if "alert" in lowered:
                    return "#e05b4b"
                if "caution" in lowered:
                    return "#f0d050"
                if "ok" in lowered:
                    return "#2ec4a0"
                return "#f0f0f0"

            team_accents_local = _team_accents(normalized_team)

            def _team_row(abbr: str, side: str) -> str:
                is_team = abbr == normalized_team
                score = final_home_score if side == "home" else final_away_score
                color = "#ffffff" if is_team else "#7a7a7a"
                weight = "800" if is_team else "400"
                row_bg = team_accents_local["row_bg"] if is_team else "transparent"
                first_cell_border = f"3px solid {team_accents_local['primary']}" if is_team else "3px solid transparent"
                inning_cells = "".join(
                    f"<td style='padding:9px 6px;border-bottom:1px solid #1e1e1e;text-align:center;color:{color};font-weight:{weight};background:{row_bg}'>{_safe(_box_value(inning.get(side)))}</td>"
                    for inning in innings
                )
                return (
                    "<tr>"
                    f"<td style='padding:10px 14px;border-bottom:1px solid #1e1e1e;color:{color};font-weight:{weight};letter-spacing:0.5px;background:{row_bg};border-left:{first_cell_border}'>{_safe(abbr)}</td>"
                    f"{inning_cells}"
                    f"<td style='padding:10px 10px;border-bottom:1px solid #1e1e1e;text-align:center;color:{color};font-weight:800;background:{row_bg}'>{_safe(_box_value(score))}</td>"
                    "</tr>"
                )

            ordered_staff = _ordered_pitchers(starters + relievers)
            final_reliever_id = str((_ordered_pitchers(relievers)[-1] if relievers else {}).get("pitcher_id") or "")
            pitcher_rows = []
            for pitcher in ordered_staff:
                role = "Reliever" if str(pitcher.get("role") or "").lower() == "reliever" else "Starter"
                finished = bool(final_reliever_id and str(pitcher.get("pitcher_id") or "") == final_reliever_id)
                signal = pitcher.get("bullpen_signal") if isinstance(pitcher.get("bullpen_signal"), dict) else {}
                rss = signal.get("rss_display_score") if signal else pitcher.get("rss_score")
                rss_label = _status_text(signal.get("rss_label") if signal else pitcher.get("rss_label") or "OK")
                stress = _fmt_num(rss, 2) if str(role).lower() == "reliever" and rss is not None else "-"
                stress_read = _rss_read(pitcher) if str(role).lower() == "reliever" else "Starter workload"
                stress_color = _rss_color(rss_label) if str(role).lower() == "reliever" and rss is not None else "#7a7a7a"
                pitcher_rows.append(
                    "<tr>"
                    f"<td style='padding:10px 10px;border-bottom:1px solid #1e1e1e;color:#ffffff;font-weight:800'>{_safe(_person_name(pitcher.get('pitcher_name') or 'Pitcher'))}</td>"
                    f"<td style='padding:10px 10px;border-bottom:1px solid #1e1e1e;color:#a0a0a0'>{_safe(role)}{' · Finished game' if finished else ''}</td>"
                    f"<td style='padding:10px 10px;border-bottom:1px solid #1e1e1e;color:#f0f0f0'>{_safe(_pitcher_line(pitcher))}</td>"
                    f"<td style='padding:10px 10px;border-bottom:1px solid #1e1e1e;color:{stress_color};font-weight:800;letter-spacing:0.3px'>{_safe(stress)}</td>"
                    f"<td style='padding:10px 10px;border-bottom:1px solid #1e1e1e;color:#a0a0a0'>{_safe(stress_read)}</td>"
                    "</tr>"
                )
            inning_header = "".join(
                f"<th style='padding:9px 6px;text-align:center;border-bottom:1px solid #1e1e1e'>{_safe(inning.get('num') or '')}</th>"
                for inning in innings
            )
            return (
                "<div style='margin-top:0;background:#0a0a0a;border:1px solid #1e1e1e;border-radius:8px;padding:16px 18px'>"
                "<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a0a0a0;font-weight:700'>Game Boxscore</div>"
                "<table style='width:100%;border-collapse:collapse;margin-top:12px;font-size:12px'>"
                "<tr style='font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#7a7a7a;font-weight:700'>"
                f"<th style='padding:9px 10px;text-align:left;border-bottom:1px solid #1e1e1e'>Team</th>{inning_header}<th style='padding:9px 10px;text-align:center;border-bottom:1px solid #1e1e1e'>R</th></tr>"
                f"{_team_row(away_team, 'away')}{_team_row(home_team, 'home')}"
                "</table>"
                "<table style='width:100%;border-collapse:collapse;margin-top:14px;font-size:12px'>"
                "<tr style='font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#7a7a7a;font-weight:700'>"
                "<th style='padding:9px 10px;text-align:left;border-bottom:1px solid #1e1e1e'>Pitcher</th><th style='padding:9px 10px;text-align:left;border-bottom:1px solid #1e1e1e'>Role</th><th style='padding:9px 10px;text-align:left;border-bottom:1px solid #1e1e1e'>Line</th><th style='padding:9px 10px;text-align:left;border-bottom:1px solid #1e1e1e'>RSS Signal</th><th style='padding:9px 10px;text-align:left;border-bottom:1px solid #1e1e1e'>Stress read</th></tr>"
                f"{''.join(pitcher_rows)}"
                "</table></div>"
            )

        def _starter_section(pitcher: dict[str, Any]) -> str:
            entry = _signal_entry(pitcher)
            state = _state(entry)
            row = _preventable_row(pitcher, entry)
            signal = _mound_signal(pitcher)
            decision = _decision_delta(pitcher, row)
            exposure = _opportunity_value(row)
            damage = _damage_risk(row)
            if damage is None:
                damage = (
                    _num(signal.get("projected_damage_probability"))
                    or _num(signal.get("damage_probability"))
                    or _num(signal.get("damageRisk"))
                    or _num(signal.get("damage_risk"))
                )
            recommended = _recommended_reliever(pitcher, row)
            status = "Pull Now" if pitcher.get("first_pull_now_inning") is not None else _status_text(pitcher.get("first_alert_status"))
            pitch_count = _entry_pitch_count(entry or {}) or pitcher.get("first_pull_now_pitch_count") or pitcher.get("first_alert_pitch_count")
            inning_label = _inning_label(row, pitcher)
            signal_away_score, signal_home_score = _score_values(row, entry, pitcher)
            signal_base_state = _entry_base_state(entry, row)
            signal_outs = _entry_outs(entry, row)
            actual_replacement = _person_name((row or {}).get("actualReplacementPitcher") or "")
            actual_inning = (row or {}).get("actualChangeInning")
            actual_pitch_count = (row or {}).get("actualChangePitchCount")
            actual_entry = _actual_removal_entry(pitcher, row)
            actual_pitch_count = actual_pitch_count or pitcher.get("actual_exit_pitch_count") or _entry_pitch_count(actual_entry or {})
            actual_inning_label = _entry_inning_label(actual_entry, actual_inning or pitcher.get("actual_exit_inning"))
            actual_away_score, actual_home_score = _score_values(None, actual_entry)
            actual_base_state = _entry_base_state(actual_entry)
            actual_outs = _entry_outs(actual_entry)
            runs_after = pitcher.get("runs_allowed_after_signal")
            if row and row.get("runsAfterModelWindow") is not None:
                runs_after = row.get("runsAfterModelWindow")
            factors = _factor_data(pitcher, entry, row)
            driver_html = _gm_rationale_text(pitcher, factors, recommended, decision, exposure, damage)
            replay_cta = (
                f"<a href='{_safe(replay_url)}' style='display:inline-block;background:#f0f0f0;color:#000000;text-decoration:none;padding:13px 30px;border-radius:8px;font-size:14px;font-weight:600;letter-spacing:-0.2px'>Open Game Replay</a>"
                if replay_url
                else ""
            )
            pitcher_name = _person_name(pitcher.get("pitcher_name") or "Starter")
            relief_detail = (
                f"Model preferred {recommended} by {_fmt_signed(decision, 2)} expected runs over leaving {pitcher_name} in for the next pocket."
                if decision is not None and "pending" not in recommended.lower()
                else "The model compared the starter against the best available relief path, but the named reliever was not resolved in this source artifact."
            )

            def _signal_badge(label: str) -> str:
                color = "#e05b4b" if label.lower() == "pull now" else "#f0d050" if label.lower() == "prep" else "#2ec4a0"
                return (
                    f"<span style='display:inline-block;margin-left:7px;border-radius:999px;background:{color};color:#000000;"
                    "padding:4px 9px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase'>"
                    f"{_safe(label)}</span>"
                )

            def _context_box(
                *,
                title: str,
                badge: str = "",
                inning: str,
                pitch_count_value: Any,
                base_state: Any,
                outs: Any,
                score_markup: str,
                emphasis: str = "",
                note: str = "",
                width_pct: str = "50%",
            ) -> str:
                emphasis_html = (
                    f"<div style='margin-top:12px;color:#e05b4b;font-size:17px;line-height:1.1;font-weight:800;letter-spacing:-0.5px'>{_safe(emphasis)}</div>"
                    if emphasis
                    else ""
                )
                note_html = f"<div style='margin-top:8px;color:#a0a0a0;font-size:11px;line-height:1.4'>{_safe(note)}</div>" if note else ""
                return (
                    f"<td style='width:{width_pct};padding:0 8px 8px 0;vertical-align:top'>"
                    "<div style='min-height:220px;background:#1a1a1a;border:1px solid #1e1e1e;border-radius:8px;padding:14px;box-sizing:border-box'>"
                    "<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a0a0a0;font-weight:700'>"
                    f"{_safe(title)}{badge}</div>"
                    f"<div style='margin-top:12px;color:#ffffff;font-size:16px;font-weight:800;letter-spacing:-0.5px'>{_safe(inning)} | Pitch {_safe(pitch_count_value if pitch_count_value else '-')}</div>"
                    "<table style='width:100%;border-collapse:collapse;margin-top:14px'><tr>"
                    f"<td style='vertical-align:middle;width:55px'>{_base_diamond(base_state)}</td>"
                    f"<td style='vertical-align:middle'>{_outs_dots(outs)}</td>"
                    "</tr></table>"
                    f"<div style='margin-top:14px;color:#f0f0f0;font-size:13px;font-weight:800'>{score_markup}</div>"
                    f"{emphasis_html}{note_html}"
                    "</div></td>"
                )

            signal_box = _context_box(
                title="Peak Model Signal",
                badge=_signal_badge(status),
                inning=inning_label,
                pitch_count_value=pitch_count,
                base_state=signal_base_state,
                outs=signal_outs,
                score_markup=_score_html(signal_away_score, signal_home_score),
                width_pct="50%",
            )
            actual_note = f"Actual replacement: {actual_replacement}" if actual_replacement else "Actual replacement not resolved in source artifact."
            damage_text = (
                "Runs after signal unavailable"
                if runs_after is None
                else f"{_fmt_num(runs_after, 0)} run{'s' if str(runs_after) != '1' else ''} of damage after model signal"
            )

            run_exposure_cell = _metric_tile(
                "Run Exposure",
                _fmt_num(exposure, 2),
                "Calibrated comparable-window exposure, not a guaranteed runs-saved claim.",
                width_pct=50,
                benchmark_html=_benchmark_meter(exposure, benchmark_context.get("run_exposure") or [], invert=True),
            )
            relief_edge_cell = _metric_tile(
                "Relief Edge",
                _fmt_signed(decision, 2),
                "Expected run advantage of the optimal relief path vs staying with the starter.",
                width_pct=50,
                benchmark_html=_benchmark_meter(decision, benchmark_context.get("decision_delta") or [], invert=True),
            )
            optimal_relief_cell = (
                "<td style='width:50%;padding:0 8px 8px 0;vertical-align:top'>"
                "<div style='min-height:220px;background:#1a1a1a;border:1px solid #1e1e1e;border-radius:8px;padding:14px;box-sizing:border-box'>"
                "<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a0a0a0;font-weight:700'>Optimal Relief Option</div>"
                f"<div style='margin-top:12px;color:#2ec4a0;font-size:24px;line-height:1.05;font-weight:800;letter-spacing:-1px'>{_safe(recommended)}</div>"
                f"<div style='margin-top:12px;color:#a0a0a0;font-size:12px;line-height:1.5'>{_safe(relief_detail)}</div>"
                "</div></td>"
            )

            actual_emphasis_html = (
                f"<div style='color:#e05b4b;font-size:18px;line-height:1.15;font-weight:800;letter-spacing:-0.5px'>{_safe(damage_text)}</div>"
                if damage_text else ""
            )
            actual_note_html = (
                f"<div style='margin-top:6px;color:#a0a0a0;font-size:12px;line-height:1.45'>{_safe(actual_note)}</div>"
                if actual_note else ""
            )
            actual_outcome_banner = (
                "<table style='width:100%;border-collapse:collapse;margin-top:0'><tr>"
                "<td style='padding:0 0 8px 0;vertical-align:top'>"
                "<div style='min-height:110px;background:#1a1a1a;border:1px solid #1e1e1e;border-radius:8px;padding:16px 18px;box-sizing:border-box'>"
                "<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a0a0a0;font-weight:700'>Actual Outcome</div>"
                "<table style='width:100%;border-collapse:collapse;margin-top:12px;table-layout:fixed'><tr>"
                "<td style='width:30%;vertical-align:middle;padding-right:14px'>"
                f"<div style='color:#ffffff;font-size:16px;font-weight:800;letter-spacing:-0.5px'>{_safe(actual_inning_label)} | Pitch {_safe(actual_pitch_count if actual_pitch_count else '-')}</div>"
                f"<div style='margin-top:10px;color:#f0f0f0;font-size:13px;font-weight:800'>{_score_html(actual_away_score, actual_home_score)}</div>"
                "</td>"
                "<td style='width:22%;vertical-align:middle;padding-right:14px'>"
                "<table style='border-collapse:collapse'><tr>"
                f"<td style='vertical-align:middle;width:55px'>{_base_diamond(actual_base_state)}</td>"
                f"<td style='vertical-align:middle;padding-left:10px'>{_outs_dots(actual_outs)}</td>"
                "</tr></table>"
                "</td>"
                "<td style='width:48%;vertical-align:middle'>"
                f"{actual_emphasis_html}{actual_note_html}"
                "</td>"
                "</tr></table>"
                "</div>"
                "</td></tr></table>"
            )

            return (
                "<div style='margin-top:20px;background:#0a0a0a;border:1px solid #1e1e1e;border-radius:8px;overflow:hidden'>"
                "<div style='padding:20px 22px;background:#000000;border-bottom:1px solid #1e1e1e'>"
                "<table style='width:100%;border-collapse:collapse'><tr>"
                "<td style='vertical-align:middle'>"
                "<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#2ec4a0;font-weight:700'>"
                "<span style='display:inline-block;width:7px;height:7px;border-radius:50%;background:#2ec4a0;margin-right:7px;vertical-align:middle'></span>"
                "Starting Pitcher</div>"
                f"<div style='margin-top:8px;font-size:22px;line-height:1.1;font-weight:800;letter-spacing:-0.8px;color:#ffffff'>{_safe(pitcher_name)}</div>"
                "</td>"
                f"<td style='vertical-align:middle;text-align:right'>{replay_cta}</td>"
                "</tr></table></div>"
                "<div style='padding:18px 22px 20px'>"
                "<table style='width:100%;border-collapse:collapse;table-layout:fixed'>"
                f"<tr>{signal_box}{run_exposure_cell}</tr>"
                f"<tr>{relief_edge_cell}{optimal_relief_cell}</tr>"
                "</table>"
                f"{actual_outcome_banner}"
                f"{driver_html}"
                f"{_driver_panel(factors, signal, pitcher=pitcher, entry=entry, row=row)}"
                "</div></div>"
            )

        def _bullpen_section() -> str:
            if not relievers:
                return ""

            def _rss_read(pitcher: dict[str, Any], signal: dict[str, Any], line: str) -> str:
                component_keys = {
                    "command": ("rss_command", "command_score", "commandStress", "command_stress"),
                    "outcome": ("rss_outcome", "outcome_score", "outcomeStress", "outcome_stress"),
                    "workload": ("rss_usage_fatigue", "rss_workload", "workload_score", "workloadStress"),
                    "handoff": ("rss_handoff_risk", "handoff_score", "handoffStress", "handoff_risk"),
                    "stuff": ("rss_stuff", "stuff_score", "stuffStress", "stuff_stress"),
                }
                components: list[tuple[str, float]] = []
                for label, keys in component_keys.items():
                    value = next((_num(signal.get(key)) for key in keys if _num(signal.get(key)) is not None), None)
                    if value is not None:
                        components.append((label, value))
                if components:
                    components.sort(key=lambda item: item[1], reverse=True)
                    driver, _value = components[0]
                    return f"Primary concern: {driver}. Appearance line: {line}."
                if signal.get("summary") and "RSS measured from" not in str(signal.get("summary")):
                    return str(signal.get("summary"))
                runs_after = pitcher.get("runs_allowed_after_first_alert")
                if runs_after is None:
                    runs_after = signal.get("runs_since")
                outcome = (
                    f"{runs_after} run{'s' if str(runs_after) != '1' else ''} after first RSS signal."
                    if runs_after is not None
                    else "No post-signal run total was attached to this appearance."
                )
                return f"{outcome} Appearance line: {line}."

            def _rss_color(label_text: str) -> str:
                lowered = (label_text or "").strip().lower()
                if "alert" in lowered:
                    return "#e05b4b"
                if "caution" in lowered:
                    return "#f0d050"
                if "ok" in lowered:
                    return "#2ec4a0"
                return "#f0f0f0"

            rows: list[str] = []
            ordered_relievers = _ordered_pitchers(relievers)
            final_reliever_id = str((ordered_relievers[-1] if ordered_relievers else {}).get("pitcher_id") or "")
            for pitcher in ordered_relievers[:8]:
                box = pitcher.get("boxscore") if isinstance(pitcher.get("boxscore"), dict) else {}
                signal = pitcher.get("bullpen_signal") if isinstance(pitcher.get("bullpen_signal"), dict) else {}
                rss = signal.get("rss_display_score") if signal else pitcher.get("rss_score")
                label = _status_text(signal.get("rss_label") if signal else pitcher.get("rss_label") or "OK")
                line = _pitcher_line(pitcher)
                finished = bool(final_reliever_id and str(pitcher.get("pitcher_id") or "") == final_reliever_id)
                role_text = "Finished game" if finished else "Relief appearance"
                stress_color = _rss_color(label)
                rows.append(
                    "<tr>"
                    f"<td style='padding:11px 10px;border-bottom:1px solid #1e1e1e;color:#ffffff;font-weight:800'>{_safe(_person_name(pitcher.get('pitcher_name') or 'Reliever'))}</td>"
                    f"<td style='padding:11px 10px;border-bottom:1px solid #1e1e1e;color:#a0a0a0'>{_safe(role_text)}</td>"
                    f"<td style='padding:11px 10px;border-bottom:1px solid #1e1e1e;color:{stress_color};font-weight:800;letter-spacing:0.3px'>{_safe(label)} {_safe(_fmt_num(rss, 2))}</td>"
                    f"<td style='padding:11px 10px;border-bottom:1px solid #1e1e1e;color:#a0a0a0'>{_safe(_rss_read(pitcher, signal, line))}</td>"
                    "</tr>"
                )
            return (
                "<div style='margin-top:20px;background:#0a0a0a;border:1px solid #1e1e1e;border-radius:8px;padding:18px 20px'>"
                "<div style='font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a0a0a0;font-weight:700'>Bullpen Stress Snapshot</div>"
                "<div style='margin-top:8px;color:#a0a0a0;font-size:11px;line-height:1.5'>RSS is a 0-1 fatigue/stress index for the relief appearance. Higher means the appearance carried more workload, command, or outcome stress.</div>"
                "<table style='width:100%;border-collapse:collapse;margin-top:12px;font-size:12px'>"
                "<tr style='color:#7a7a7a;text-transform:uppercase;letter-spacing:2px;font-size:10px;font-weight:700'>"
                "<th style='padding:9px 10px;text-align:left;border-bottom:1px solid #1e1e1e'>Pitcher</th><th style='padding:9px 10px;text-align:left;border-bottom:1px solid #1e1e1e'>Role in game</th><th style='padding:9px 10px;text-align:left;border-bottom:1px solid #1e1e1e'>RSS</th><th style='padding:9px 10px;text-align:left;border-bottom:1px solid #1e1e1e'>Stress read</th>"
                "</tr>"
                f"{''.join(rows)}"
                "</table></div>"
            )

        starter_sections = "".join(_starter_section(pitcher) for pitcher in starters)
        if not starter_sections:
            starter_sections = (
                "<div style='margin-top:22px;background:#0a0a0a;border:1px solid #1e1e1e;border-radius:8px;padding:18px 20px;color:#a0a0a0'>"
                "No starter decision window was available for this team game.</div>"
            )
        team_accents = _team_accents(normalized_team)
        _logo_accent = team_accents["primary"]
        logo_svg = (
            "<svg viewBox='0 0 565 115' xmlns='http://www.w3.org/2000/svg' role='img' "
            "aria-label='Baseball brAIn' width='320' height='65' style='display:block;margin-left:auto'>"
            "<text x='20' y='82' font-family='&quot;Helvetica Neue&quot;,Helvetica,Arial,sans-serif' "
            "font-size='36' font-weight='300' letter-spacing='6' fill='#FFFFFF'>BASEBALL</text>"
            "<text x='322' y='82' font-family='&quot;Helvetica Neue&quot;,Helvetica,Arial,sans-serif' "
            "font-size='84' font-weight='700' letter-spacing='-1' fill='#FFFFFF' fill-opacity='0.70'>"
            "<tspan fill-opacity='0.70'>br</tspan>"
            f"<tspan fill='{_logo_accent}' fill-opacity='1'>AI</tspan>"
            "<tspan fill-opacity='0.70'>n</tspan>"
            "</text>"
            "<polygon points='277,17 312,52 277,87 242,52' fill='none' stroke='#FFFFFF' stroke-width='2.5' stroke-linejoin='miter'/>"
            f"<line x1='269' y1='52' x2='285' y2='52' stroke='{_logo_accent}' stroke-width='1.8' stroke-linecap='round'/>"
            f"<line x1='277' y1='44' x2='277' y2='60' stroke='{_logo_accent}' stroke-width='1.8' stroke-linecap='round'/>"
            "<text text-anchor='middle' x='282' y='110' font-family='&quot;Helvetica Neue&quot;,Helvetica,Arial,sans-serif' "
            "font-size='15' font-weight='400' letter-spacing='3.5' fill='#ffffff'>"
            "ADVANCED BASEBALL INTELLIGENCE</text>"
            "</svg>"
        )
        return (
            "<html><body style='margin:0;background:#000000;font-family:\"Helvetica Neue\",Helvetica,Arial,sans-serif;color:#f0f0f0;font-size:16px;line-height:24px'>"
            "<div style='max-width:860px;margin:0 auto;padding:24px'>"
            "<div style='background:#000000;border:1px solid #1e1e1e;color:#ffffff;border-radius:8px 8px 0 0;padding:28px 30px'>"
            "<table style='width:100%;border-collapse:collapse'><tr>"
            "<td style='vertical-align:middle'>"
            f"<div style='font-size:56px;line-height:1.08;font-weight:800;letter-spacing:-2.5px;color:#ffffff'>{_safe(opponent_label)}</div>"
            f"<div style='margin-top:12px;color:#a0a0a0;font-size:14px;line-height:1.3'>{_safe(str(recap.get('date') or ''))} | Final: <span style='color:{team_accents['label']};font-weight:800;font-size:14px;line-height:1.3'>{_safe(normalized_team)} {_safe(_team_score_text)}</span> <span style='color:#ffffff;font-weight:800;font-size:14px;line-height:1.3'>{_safe(opponent)} {_safe(_opp_score_text)}</span></div>"
            "</td>"
            f"<td style='vertical-align:middle;text-align:right;width:320px'>{logo_svg}</td>"
            "</tr></table>"
            "</div>"
            "<div style='background:#000000;border:1px solid #1e1e1e;border-top:none;border-radius:0 0 8px 8px;padding:22px 24px 26px'>"
            f"{_game_boxscore_section()}"
            f"{starter_sections}"
            "<div style='margin-top:24px;color:#7a7a7a;font-size:11px;line-height:1.5'>"
            "Model note: Relief Edge and Run Exposure are calibrated decision-window estimates, not guaranteed counterfactual runs saved. Club-confirmed bullpen availability is not available unless supplied by the team."
            "</div>"
            "</div>"
            "</div></body></html>"
        )

    def _pitching_recap_email_html(
        recap: dict[str, Any],
        team: str,
        replay_url: str | None = None,
        replay_payload: dict[str, Any] | None = None,
        preventable_lookup: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        return _pitching_recap_email_html_v2(
            recap,
            team,
            replay_url=replay_url,
            replay_payload=replay_payload,
            preventable_lookup=preventable_lookup,
        )
        normalized_team = _normalize_pitching_recap_team(team) or str(team or "").upper()
        home_team = str(recap.get("home_team") or "")
        away_team = str(recap.get("away_team") or "")
        final_home_score = recap.get("final_home_score")
        final_away_score = recap.get("final_away_score")
        pitchers = [dict(pitcher) for pitcher in (recap.get("starters") or []) if isinstance(pitcher, dict)]
        starters = [pitcher for pitcher in pitchers if str(pitcher.get("role") or "").lower() != "reliever"]
        relievers = [pitcher for pitcher in pitchers if str(pitcher.get("role") or "").lower() == "reliever"]
        entries = [
            dict(entry)
            for entry in ((replay_payload or {}).get("entries") or [])
            if isinstance(entry, dict)
        ]
        entries_by_pitcher: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in entries:
            snapshot = entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {}
            pitcher_id = str(snapshot.get("pitcher_id") or "")
            if pitcher_id:
                entries_by_pitcher[pitcher_id].append(entry)

        def _safe(value: Any) -> str:
            return html.escape(str(value if value is not None else ""), quote=True)

        def _num(value: Any) -> float | None:
            try:
                if value in (None, ""):
                    return None
                number = float(value)
            except Exception:
                return None
            if math.isnan(number) or math.isinf(number):
                return None
            return number

        def _intish(value: Any) -> int | None:
            number = _num(value)
            return int(number) if number is not None else None

        def _fmt_num(value: Any, digits: int = 1, fallback: str = "—") -> str:
            number = _num(value)
            if number is None:
                return fallback
            if digits <= 0:
                return f"{number:.0f}"
            return f"{number:.{digits}f}"

        def _fmt_signed(value: Any, digits: int = 2, fallback: str = "—") -> str:
            number = _num(value)
            if number is None:
                return fallback
            return f"{number:+.{digits}f}"

        def _fmt_pct(value: Any, fallback: str = "—") -> str:
            number = _num(value)
            if number is None:
                return fallback
            if abs(number) <= 1.0:
                number *= 100.0
            return f"{number:.0f}%"

        def _runs_opportunity_phrase(value: Any) -> str:
            number = _num(value)
            if number is None:
                return "Run-saving opportunity is not available for this window."
            if number >= 0.50:
                return f"High-priority opportunity: changing here projected to prevent about {number:.2f} runs."
            if number >= 0.20:
                return f"Review-worthy opportunity: changing here projected to prevent about {number:.2f} runs."
            if number > 0:
                return f"Small edge: changing here projected to prevent about {number:.2f} runs."
            if number < 0:
                return "Model did not favor a change after bullpen quality and usage cost were included."
            return "No meaningful run-saving edge on this window."

        def _opportunity_value(row: dict[str, Any] | None) -> Any:
            if not isinstance(row, dict):
                return None
            calibrated = row.get("projectedPreventableRuns")
            if calibrated is not None:
                return calibrated
            return row.get("modelImpliedRunsSaved")

        def _opportunity_phrase(row: dict[str, Any] | None) -> str:
            if not isinstance(row, dict):
                return _runs_opportunity_phrase(None)
            value = _opportunity_value(row)
            phrase = _runs_opportunity_phrase(value)
            if row.get("projectedPreventableRuns") is None and row.get("modelImpliedRunsSaved") is not None:
                return f"{phrase} Directional estimate; calibrated comparable-window sample is not yet available."
            return phrase

        def _degradation_phrase(value: Any) -> str:
            number = _num(value)
            if number is None:
                return "Starter condition unavailable"
            if number >= 2.0:
                return "severe late-outing decline"
            if number >= 1.25:
                return "clear decline"
            if number >= 0.75:
                return "moderate decline"
            return "stable enough to continue"

        def _strike_phrase(value: Any) -> str:
            number = _num(value)
            if number is None:
                return "strike-throwing unavailable"
            if number <= 1.0:
                number *= 100.0
            if number >= 65:
                return "strike throwing held"
            if number >= 55:
                return "strike throwing was playable"
            return "strike throwing was under pressure"

        def _leverage_phrase(value: Any) -> str:
            number = _num(value)
            if number is None:
                return "game pressure unavailable"
            if number >= 1.5:
                return "high-leverage pocket"
            if number >= 1.0:
                return "meaningful leverage"
            return "lower-leverage pocket"

        def _fmt_ip(value: Any) -> str:
            if value is None or value == "":
                return "—"
            return str(value)

        def _status_text(value: Any) -> str:
            return str(value or "STAY").replace("_", " ").upper()

        def _pitching_value(value: Any, fallback: str = "—") -> str:
            if value is None or value == "":
                return fallback
            return str(value)

        def _pitch_type_label(value: Any) -> str:
            pitch_type = str(value or "").upper()
            labels = {
                "FF": "Four-Seam Fastball",
                "FA": "Fastball",
                "SI": "Sinker",
                "SL": "Slider",
                "ST": "Sweeper",
                "CH": "Changeup",
                "CU": "Curveball",
                "KC": "Knuckle Curve",
                "FC": "Cutter",
                "FS": "Splitter",
                "FO": "Forkball",
                "KN": "Knuckleball",
                "SV": "Slurve",
            }
            return labels.get(pitch_type, str(value or "Pitch"))

        def _state(entry: dict[str, Any] | None) -> dict[str, Any]:
            if not isinstance(entry, dict):
                return {}
            snapshot = entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {}
            state = snapshot.get("starter_state") if isinstance(snapshot.get("starter_state"), dict) else {}
            return state

        def _snapshot(entry: dict[str, Any] | None) -> dict[str, Any]:
            if not isinstance(entry, dict):
                return {}
            return entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {}

        def _entry_pitch_count(entry: dict[str, Any]) -> int | None:
            state = _state(entry)
            snapshot = _snapshot(entry)
            return _intish(
                state.get("official_pitch_count_in_game")
                or state.get("pitch_count_in_game")
                or snapshot.get("pitch_count")
            )

        def _pitcher_entries(pitcher: dict[str, Any]) -> list[dict[str, Any]]:
            return entries_by_pitcher.get(str(pitcher.get("pitcher_id") or ""), [])

        def _signal_entry(pitcher: dict[str, Any]) -> dict[str, Any] | None:
            pitcher_entries = _pitcher_entries(pitcher)
            if not pitcher_entries:
                return None
            target_pc = _intish(pitcher.get("first_pull_now_pitch_count") or pitcher.get("first_alert_pitch_count"))
            if target_pc is not None:
                exact = [entry for entry in pitcher_entries if _entry_pitch_count(entry) == target_pc]
                if exact:
                    return exact[0]
                nearby = [
                    entry
                    for entry in pitcher_entries
                    if _entry_pitch_count(entry) is not None and abs(int(_entry_pitch_count(entry) or 0) - target_pc) <= 2
                ]
                if nearby:
                    nearby.sort(key=lambda entry: abs(int(_entry_pitch_count(entry) or 0) - target_pc))
                    return nearby[0]
            return pitcher_entries[-1]

        def _preventable_row(pitcher: dict[str, Any], entry: dict[str, Any] | None) -> dict[str, Any] | None:
            if not isinstance(preventable_lookup, dict):
                return None
            pitcher_id = str(pitcher.get("pitcher_id") or "")
            game_id = str(recap.get("game_id") or "")
            target_pc = _entry_pitch_count(entry or {}) or _intish(pitcher.get("first_pull_now_pitch_count") or pitcher.get("first_alert_pitch_count"))
            if game_id and pitcher_id and target_pc is not None:
                for offset in (0, -1, 1, -2, 2, -3, 3):
                    key = f"{game_id}:{pitcher_id}:{target_pc + offset}"
                    row = preventable_lookup.get(key)
                    if isinstance(row, dict):
                        return row
            if game_id and pitcher_id:
                row = preventable_lookup.get(f"{game_id}:{pitcher_id}")
                if isinstance(row, dict):
                    return row
            return None

        def _stuff_score(entry: dict[str, Any] | None) -> int | None:
            state = _state(entry)
            deg = _num(state.get("enhanced_degradation_score") or state.get("degradation_score"))
            if deg is None:
                return None
            return max(0, min(100, int(round(100.0 - deg * 22.0))))

        def _signal_card(pitcher: dict[str, Any], entry: dict[str, Any] | None) -> str:
            state = _state(entry)
            row = _preventable_row(pitcher, entry)
            pull_pc = pitcher.get("first_pull_now_pitch_count")
            alert_pc = pitcher.get("first_alert_pitch_count")
            action_pc = pull_pc if pull_pc is not None else alert_pc
            action_inn = pitcher.get("first_pull_now_inning") if pull_pc is not None else pitcher.get("first_alert_inning")
            signal = "Pull Now" if pull_pc is not None else _status_text(pitcher.get("first_alert_status")) if alert_pc is not None else "No action point"
            exit_text = "Exit timing unavailable"
            if pitcher.get("actual_exit_inning") is not None:
                exit_text = f"Pulled inn {pitcher.get('actual_exit_inning')}, PC {pitcher.get('actual_exit_pitch_count') or '—'}"
            runs = pitcher.get("runs_allowed_after_signal")
            runs_text = "Damage after signal unavailable" if runs is None else f"Damage after signal: {runs} run{'s' if str(runs) != '1' else ''}"
            if action_inn is not None:
                trigger_text = f"{signal} fired inn {action_inn}, PC {action_pc or '—'}"
            else:
                trigger_text = signal
            preventable_text = _opportunity_phrase(row)
            decision_context = (
                f"{_degradation_phrase(state.get('enhanced_degradation_score') or state.get('degradation_score')).capitalize()}; "
                f"{_leverage_phrase(state.get('leverage_index'))}."
            )
            return (
                "<div style='margin-top:18px;padding:18px;background:#fbfaf5;border:1px solid #d4d0c8;border-radius:12px'>"
                "<div style='font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#0f172a;font-weight:800'>Mound Signal</div>"
                f"<div style='margin-top:10px;color:#334155;line-height:1.55;font-size:16px'>{_safe(trigger_text)}. {_safe(exit_text)}. <strong>{_safe(runs_text)}</strong>.</div>"
                f"<div style='margin-top:8px;color:#6b7280;font-size:13px'>{_safe(decision_context)} Stuff {_safe(_fmt_num(_stuff_score(entry), 0))}/100. {_safe(preventable_text)}</div>"
                "</div>"
            )

        def _metric_chip(label: str, value: str, detail: str = "") -> str:
            return (
                "<div style='background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:12px'>"
                f"<div style='font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:#94a3b8;font-weight:800'>{_safe(label)}</div>"
                f"<div style='margin-top:6px;font-size:20px;color:#0f172a;font-weight:900'>{_safe(value)}</div>"
                f"<div style='margin-top:4px;color:#64748b;font-size:12px'>{_safe(detail)}</div>"
                "</div>"
            )

        def _model_grid(pitcher: dict[str, Any], entry: dict[str, Any] | None) -> str:
            state = _state(entry)
            row = _preventable_row(pitcher, entry)
            decay = (_num(state.get("inning_decay_factor")) or 0.0) + (_num(state.get("tto_decay_factor")) or 0.0)
            cards = [
                _metric_chip(
                    "Run-Saving Opportunity",
                    _fmt_signed(_opportunity_value(row), 2) if isinstance(row, dict) and _opportunity_value(row) is not None else "Unavailable",
                    _opportunity_phrase(row),
                ),
                _metric_chip(
                    "Starter Condition",
                    _degradation_phrase(state.get("enhanced_degradation_score") or state.get("degradation_score")).capitalize(),
                    f"Model read {_fmt_num(state.get('enhanced_degradation_score') or state.get('degradation_score'), 2)} · relative severity {_fmt_pct(state.get('normalized_degradation_score'))}",
                ),
                _metric_chip(
                    "Fatigue Pattern",
                    _fmt_num(decay, 2),
                    f"Inning history {_fmt_num(state.get('inning_decay_factor'), 2)} · times-through-order history {_fmt_num(state.get('tto_decay_factor'), 2)}",
                ),
                _metric_chip(
                    "Strike Quality",
                    _fmt_pct(state.get("strike_rate_10") if state.get("strike_rate_10") is not None else (1 - float(state.get("ball_rate_10") or 0))),
                    f"{_strike_phrase(state.get('strike_rate_10') if state.get('strike_rate_10') is not None else (1 - float(state.get('ball_rate_10') or 0)))} · zone miss {_fmt_num(state.get('zone_miss_distance_10'), 2)} ft",
                ),
                _metric_chip(
                    "Stuff Snapshot",
                    f"{_fmt_num(_stuff_score(entry), 0)}/100",
                    f"Fastball {_fmt_num(state.get('velo_mean_10') or state.get('velo_mean_5'), 1)} mph · spin {_fmt_num(state.get('spin_mean_10') or state.get('spin_mean_5'), 0)} rpm",
                ),
                _metric_chip(
                    "Game Pressure",
                    _leverage_phrase(state.get("leverage_index")).capitalize(),
                    f"Leverage {_fmt_num(state.get('leverage_index'), 2)} · relief edge {_fmt_signed(row.get('decisionDelta'), 2) if isinstance(row, dict) else '—'}",
                ),
            ]
            return (
                "<div style='margin-top:14px;padding:16px;border:1px solid #e5e7eb;border-radius:16px;background:#f8fafc'>"
                "<div style='font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#9a3412;font-weight:900'>Baseball Read</div>"
                "<div style='display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px'>"
                f"{''.join(cards)}"
                "</div></div>"
            )

        def _pitch_mix_summary(pitcher: dict[str, Any]) -> tuple[str, list[str]]:
            pitcher_entries = _pitcher_entries(pitcher)
            if not pitcher_entries:
                return "Arsenal data unavailable", []
            groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "velo": []})
            for entry in pitcher_entries:
                snapshot = _snapshot(entry)
                pitch_type = _pitch_type_label(snapshot.get("pitch_type") or snapshot.get("pitch_name"))
                groups[pitch_type]["count"] += 1
                velo = _num(snapshot.get("release_speed") or snapshot.get("start_speed"))
                if velo is not None:
                    groups[pitch_type]["velo"].append(velo)
            total = sum(int(group["count"]) for group in groups.values())
            ranked = sorted(groups.items(), key=lambda item: int(item[1]["count"]), reverse=True)
            headline_parts = [
                f"{name} {round(int(group['count']) * 100 / total)}%"
                for name, group in ranked[:3]
                if total
            ]
            lines = []
            for name, group in ranked[:5]:
                count = int(group["count"])
                pct = round(count * 100 / total) if total else 0
                velo_values = group.get("velo") or []
                velo = sum(velo_values) / len(velo_values) if velo_values else None
                lines.append(f"{name} ({pct}%) at {_fmt_num(velo, 1)} mph")
            return f"Arsenal mix: {', '.join(headline_parts) if headline_parts else 'pitch mix unavailable'}", lines

        def _component_contributors(state: dict[str, Any]) -> str:
            raw = state.get("component_contributions")
            contributors: list[tuple[str, float]] = []
            if isinstance(raw, dict):
                for key, value in raw.items():
                    number = _num(value)
                    if number is not None:
                        contributors.append((str(key).replace("_", " ").title(), number))
            if not contributors:
                for label, keys in {
                    "Velocity": ["velocity_contribution", "velo_contribution"],
                    "Command": ["command_contribution", "location_contribution"],
                    "Whiff": ["whiff_contribution"],
                    "Contact": ["contact_contribution"],
                    "Decay": ["decay_contribution"],
                }.items():
                    number = next((_num(state.get(key)) for key in keys if _num(state.get(key)) is not None), None)
                    if number is not None:
                        contributors.append((label, number))
            contributors.sort(key=lambda item: abs(item[1]), reverse=True)
            if not contributors:
                return "Top model contributors unavailable from source artifact."
            return "Top model contributors: " + ", ".join(f"{label} {_fmt_signed(value, 2)}" for label, value in contributors[:5])

        def _starter_bullets(pitcher: dict[str, Any], entry: dict[str, Any] | None) -> str:
            state = _state(entry)
            row = _preventable_row(pitcher, entry)
            arsenal_headline, arsenal_lines = _pitch_mix_summary(pitcher)
            alert_inn = pitcher.get("first_alert_inning")
            pull_inn = pitcher.get("first_pull_now_inning")
            fatigue_headline = (
                f"Early degradation alert inning {alert_inn} — Pull Now by inning {pull_inn}"
                if alert_inn is not None and pull_inn is not None
                else f"Action point reached in inning {pull_inn}"
                if pull_inn is not None
                else "No Pull Now action point"
            )
            fatigue_detail = (
                f"{pitcher.get('pitch_count') or '—'} pitches, TTO {_fmt_num(state.get('times_through_order'), 0)}. "
                f"The model read this as {_degradation_phrase(state.get('enhanced_degradation_score') or state.get('degradation_score'))}; "
                f"pitcher-specific inning/TTO history added {_fmt_num((_num(state.get('inning_decay_factor')) or 0) + (_num(state.get('tto_decay_factor')) or 0), 2)} points of fatigue pressure."
            )
            stuff_headline = "Stuff — fatigue and arsenal movement"
            stuff_detail = (
                f"Game stuff score {_fmt_num(_stuff_score(entry), 0)}/100, where lower means the current arsenal looked less playable than baseline. "
                f"Fastball velocity {_fmt_num(state.get('velo_mean_10') or state.get('velo_mean_5'), 1)} vs baseline {_fmt_num(state.get('seasonal_velo_baseline'), 1)}; "
                f"fastball spin {_fmt_num(state.get('spin_mean_10') or state.get('spin_mean_5'), 0)} vs baseline {_fmt_num(state.get('seasonal_spin_baseline'), 0)}. "
                f"Swinging-strike rate {_fmt_pct(state.get('whiff_rate_15'))}."
            )
            command_headline = "Command and contact — whether the strikes were still competitive"
            strike_rate = state.get("strike_rate_10")
            if strike_rate is None and state.get("ball_rate_10") is not None:
                strike_rate = 1 - float(state.get("ball_rate_10") or 0.0)
            command_detail = (
                f"Strike rate {_fmt_pct(strike_rate)} · called-strike rate {_fmt_pct(state.get('called_strike_rate_15'))} · "
                f"zone miss {_fmt_num(state.get('zone_miss_distance_10'), 2)} ft · command spread {_fmt_num(state.get('location_dispersion_10'), 2)} · "
                f"hard contact {_fmt_pct(state.get('hard_contact_rate_15'))}."
            )
            decision_headline = "Decision — whether the bullpen gave the club a better path"
            decision_detail = (
                f"{_opportunity_phrase(row)} "
                f"Comparable historical windows produced a damage probability of {_fmt_pct(row.get('projectedDamageProbability')) if isinstance(row, dict) else '—'}; "
                f"this was a {_leverage_phrase(state.get('leverage_index'))}. {_component_contributors(state)}"
            )

            def _bullet(index: int, label: str, headline: str, detail: str, children: list[str] | None = None) -> str:
                child_html = "".join(f"<li>{_safe(item)}</li>" for item in (children or []))
                child_block = f"<ul style='margin:8px 0 0 20px;color:#475569'>{child_html}</ul>" if child_html else ""
                return (
                    "<div style='margin-top:18px'>"
                    f"<div style='font-size:19px;color:#0f172a;font-weight:900'><span style='color:#9a3412'>{index}. {label}</span> — {_safe(headline)}</div>"
                    f"<div style='margin-top:7px;color:#475569;line-height:1.55'>{_safe(detail)}</div>"
                    f"{child_block}"
                    "</div>"
                )

            return "".join(
                [
                    _bullet(1, "ARSENAL", arsenal_headline, f"{len(arsenal_lines) or '—'} pitch-type groups tracked through replay.", arsenal_lines),
                    _bullet(2, "FATIGUE", fatigue_headline, fatigue_detail),
                    _bullet(3, "STUFF", stuff_headline, stuff_detail),
                    _bullet(4, "COMMAND", command_headline, command_detail),
                    _bullet(5, "DECISION", decision_headline, decision_detail),
                ]
            )

        def _signal_cell(pitcher: dict[str, Any]) -> str:
            role = str(pitcher.get("role") or "")
            if role.lower() == "reliever":
                score = pitcher.get("rss_score")
                label = _status_text(pitcher.get("rss_label") or "OK")
                if score is None:
                    return f"{label}"
                try:
                    return f"{label} {float(score):.2f}"
                except Exception:
                    return f"{label} {score}"
            signal = _status_text(pitcher.get("peak_status") or "STAY")
            if pitcher.get("first_pull_now_inning") is not None:
                return f"{signal} · Inn {pitcher.get('first_pull_now_inning')} P{pitcher.get('first_pull_now_pitch_count') or '—'}"
            if pitcher.get("first_alert_inning") is not None:
                return f"{signal} · Inn {pitcher.get('first_alert_inning')} P{pitcher.get('first_alert_pitch_count') or '—'}"
            return signal

        def _staff_rows() -> str:
            rows: list[str] = []
            for pitcher in pitchers:
                role = str(pitcher.get("role") or "Pitcher")
                box = pitcher.get("boxscore") if isinstance(pitcher.get("boxscore"), dict) else {}
                rows.append(
                    "<tr>"
                    f"<td style='padding:9px 10px;border-bottom:1px solid #e5e7eb;font-weight:800;color:#0f172a'>{_safe(pitcher.get('pitcher_name') or 'Unknown')}</td>"
                    f"<td style='padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center'>{_safe(_pitching_value(box.get('ip') or pitcher.get('innings_pitched')))}</td>"
                    f"<td style='padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center'>{_safe(_pitching_value(box.get('h') if box else pitcher.get('hits_allowed')))}</td>"
                    f"<td style='padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center'>{_safe(_pitching_value(box.get('r') if box else pitcher.get('runs_allowed_total')))}</td>"
                    f"<td style='padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center'>{_safe(_pitching_value(box.get('er') if box else pitcher.get('earned_runs_total')))}</td>"
                    f"<td style='padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center'>{_safe(_pitching_value(box.get('bb') if box else pitcher.get('walks')))}</td>"
                    f"<td style='padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center'>{_safe(_pitching_value(box.get('so') if box else pitcher.get('strikeouts')))}</td>"
                    f"<td style='padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center'>{_safe(_pitching_value(box.get('hr') if box else pitcher.get('home_runs')))}</td>"
                    f"<td style='padding:9px 10px;border-bottom:1px solid #e5e7eb;color:#9a3412;font-weight:800'>{_safe(_signal_cell(pitcher))}</td>"
                    f"<td style='padding:9px 10px;border-bottom:1px solid #e5e7eb;color:#64748b'>{_safe(role)}</td>"
                    "</tr>"
                )
            return "".join(rows) or '<tr><td colspan="10" style="padding:12px">No pitching staff data available.</td></tr>'

        def _starter_sections() -> str:
            sections: list[str] = []
            for pitcher in starters:
                entry = _signal_entry(pitcher)
                opponent = away_team if normalized_team == home_team else home_team
                box = pitcher.get("boxscore") if isinstance(pitcher.get("boxscore"), dict) else {}
                stat_line = (
                    f"{_pitching_value(box.get('ip') or pitcher.get('innings_pitched'))} IP · "
                    f"{_pitching_value(box.get('h') if box else pitcher.get('hits_allowed'))} H · "
                    f"{_pitching_value(box.get('r') if box else pitcher.get('runs_allowed_total'))} R · "
                    f"{_pitching_value(box.get('er') if box else pitcher.get('earned_runs_total'))} ER · "
                    f"{_pitching_value(box.get('bb') if box else pitcher.get('walks'))} BB · "
                    f"{_pitching_value(box.get('so') if box else pitcher.get('strikeouts'))} SO · "
                    f"{_pitching_value(box.get('hr') if box else pitcher.get('home_runs'))} HR"
                )
                sections.append(
                    "<div style='margin:26px 0 0;padding:20px;background:#fff;border:1px solid #e5e7eb;border-radius:16px'>"
                    f"<div style='font-size:30px;font-weight:900;color:#0f172a;line-height:1.1'>{_safe(pitcher.get('pitcher_name') or 'Starter')} vs. {_safe(opponent)}</div>"
                    f"<div style='margin-top:8px;color:#475569;font-size:15px'>{_safe(str(recap.get('date') or ''))} · {_safe(away_team)} {_safe(final_away_score if final_away_score is not None else '—')}, {_safe(home_team)} {_safe(final_home_score if final_home_score is not None else '—')}</div>"
                    f"<div style='margin-top:10px;color:#334155;font-size:16px;font-weight:800'>{_safe(stat_line)}</div>"
                    f"{_signal_card(pitcher, entry)}"
                    f"{_model_grid(pitcher, entry)}"
                    f"{_starter_bullets(pitcher, entry)}"
                    "</div>"
                )
            return "".join(sections)

        def _reliever_section() -> str:
            if not relievers:
                return ""
            rows: list[str] = []
            for pitcher in relievers:
                alert = "No pitch-level RSS trigger timing reconstructed"
                bullpen_signal = pitcher.get("bullpen_signal") if isinstance(pitcher.get("bullpen_signal"), dict) else {}
                trigger_inn = bullpen_signal.get("trigger_inning") if bullpen_signal else pitcher.get("first_alert_inning")
                trigger_pc = bullpen_signal.get("trigger_pitch_count") if bullpen_signal else pitcher.get("first_alert_pitch_count")
                trigger_level = bullpen_signal.get("trigger_level") if bullpen_signal else pitcher.get("first_alert_status")
                if trigger_inn is not None:
                    alert = f"{_status_text(trigger_level)} in inning {trigger_inn}, pitch {trigger_pc or '—'}"
                elif trigger_level:
                    alert = f"{_status_text(trigger_level)} measured from appearance state; pitch-level trigger timing not reconstructed"
                runs_after = _pitching_value(pitcher.get("runs_allowed_after_first_alert"), "NA")
                if runs_after == "NA" and bullpen_signal:
                    runs_after = _pitching_value(bullpen_signal.get("runs_since"), "NA")
                if runs_after != "NA":
                    runs_after = f"{runs_after} run{'s' if str(runs_after) != '1' else ''} after RSS signal"
                box = pitcher.get("boxscore") if isinstance(pitcher.get("boxscore"), dict) else {}
                line = (
                    f"{_pitching_value(box.get('ip') or pitcher.get('innings_pitched'))} IP, "
                    f"{_pitching_value(box.get('h') if box else pitcher.get('hits_allowed'))} H, "
                    f"{_pitching_value(box.get('r') if box else pitcher.get('runs_allowed_total'))} R, "
                    f"{_pitching_value(box.get('bb') if box else pitcher.get('walks'))} BB, "
                    f"{_pitching_value(box.get('so') if box else pitcher.get('strikeouts'))} K"
                )
                intel = "Appearance-level RSS measured from command, whiff, contact, and workload state."
                if bullpen_signal:
                    rss = _fmt_num(bullpen_signal.get("rss_display_score") or pitcher.get("rss_score"), 2)
                    intel = f"Peak RSS {rss}; command/control and usage profile evaluated from official pitch facts."
                rows.append(
                    "<tr>"
                    f"<td style='padding:12px;border-bottom:1px solid #e5e7eb;font-weight:800;color:#0f172a'>{_safe(pitcher.get('pitcher_name') or 'Reliever')}</td>"
                    f"<td style='padding:12px;border-bottom:1px solid #e5e7eb;color:#64748b'>{_safe(line)}</td>"
                    f"<td style='padding:12px;border-bottom:1px solid #e5e7eb;color:#d97706;font-weight:900'>{_safe(_signal_cell(pitcher))}</td>"
                    f"<td style='padding:12px;border-bottom:1px solid #e5e7eb;color:#475569'>{_safe(intel)}</td>"
                    f"<td style='padding:12px;border-bottom:1px solid #e5e7eb;color:#475569'>{_safe(alert)}<br><strong>{_safe(runs_after)}</strong></td>"
                    "</tr>"
                )
            return (
                "<div style='margin:26px 0 0'>"
                "<div style='font-size:14px;font-weight:800;color:#0f172a;text-transform:uppercase;letter-spacing:1.4px;border-bottom:3px solid #1a1a2e;padding-bottom:7px'>Bullpen RSS</div>"
                "<table style='width:100%;border-collapse:collapse;margin-top:8px;font-size:13px'>"
                "<tr style='font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.8px'>"
                "<th style='padding:8px;text-align:left'>Pitcher</th><th style='padding:8px;text-align:left'>Line</th><th style='padding:8px;text-align:left'>RSS</th><th style='padding:8px;text-align:left'>Timing</th><th style='padding:8px;text-align:left'>Outcome</th>"
                "</tr>"
                f"{''.join(rows)}"
                "</table></div>"
            )

        replay_cta = (
            f"<p style='margin:20px 0 0'><a href='{replay_url}' "
            "style='display:inline-block;background:#1d4ed8;color:#fff;text-decoration:none;padding:10px 16px;border-radius:10px;font-weight:600'>Open Pitch-by-Pitch Replay</a></p>"
            if replay_url
            else ""
        )
        return (
            "<html><body style='margin:0;background:#f8f6f0;font-family:Georgia,Times New Roman,serif;color:#111827'>"
            "<div style='max-width:900px;margin:0 auto;padding:28px'>"
            f"<div style='font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700'>Pitcher Intel · Finalized Recap</div>"
            f"<h1 style='margin:10px 0 6px;font-size:34px;line-height:1.1'>brAIn — {normalized_team} Recap</h1>"
            f"<div style='font-size:15px;color:#475569'>{away_team} @ {home_team} · {recap.get('date') or ''}</div>"
            f"<div style='margin-top:14px;font-size:24px;font-weight:700'>{away_team} {final_away_score if final_away_score is not None else '—'} · {home_team} {final_home_score if final_home_score is not None else '—'}</div>"
            "<div style='margin-top:22px;background:#fff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'>"
            "<table style='width:100%;border-collapse:collapse;font-size:14px'>"
            "<thead><tr style='background:#0f172a;color:#fff;text-align:left'>"
            "<th style='padding:10px'>Pitcher</th><th style='padding:10px;text-align:center'>IP</th><th style='padding:10px;text-align:center'>H</th><th style='padding:10px;text-align:center'>R</th><th style='padding:10px;text-align:center'>ER</th><th style='padding:10px;text-align:center'>BB</th><th style='padding:10px;text-align:center'>SO</th><th style='padding:10px;text-align:center'>HR</th><th style='padding:10px'>Signal</th><th style='padding:10px'>Role</th>"
            "</tr></thead>"
            f"<tbody>{_staff_rows()}</tbody>"
            "</table></div>"
            f"{_starter_sections()}"
            f"{_reliever_section()}"
            f"{replay_cta}"
            "</div></body></html>"
        )

    def _pitching_recap_email_text(
        recap: dict[str, Any],
        team: str,
        replay_url: str | None = None,
        replay_payload: dict[str, Any] | None = None,
        preventable_lookup: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        normalized_team = _normalize_pitching_recap_team(team) or str(team or "").upper()
        home_team = str(recap.get("home_team") or "")
        away_team = str(recap.get("away_team") or "")
        opponent = away_team if normalized_team == home_team else home_team

        def _num(value: Any) -> float | None:
            try:
                if value in (None, ""):
                    return None
                number = float(value)
            except Exception:
                return None
            if math.isnan(number) or math.isinf(number):
                return None
            return number

        def _fmt_num(value: Any, digits: int = 2, fallback: str = "-") -> str:
            number = _num(value)
            if number is None:
                return fallback
            return f"{number:.{digits}f}"

        def _fmt_signed(value: Any, digits: int = 2, fallback: str = "-") -> str:
            number = _num(value)
            if number is None:
                return fallback
            return f"{number:+.{digits}f}"

        def _fmt_pct(value: Any, fallback: str = "-") -> str:
            number = _num(value)
            if number is None:
                return fallback
            if abs(number) <= 1.0:
                number *= 100.0
            return f"{number:.0f}%"

        def _row_for(pitcher: dict[str, Any]) -> dict[str, Any] | None:
            if not isinstance(preventable_lookup, dict):
                return None
            game_id = str(recap.get("game_id") or "")
            pitcher_id = str(pitcher.get("pitcher_id") or "")
            if not game_id or not pitcher_id:
                return None
            pitch_count = pitcher.get("first_pull_now_pitch_count") or pitcher.get("first_alert_pitch_count")
            if pitch_count is not None:
                try:
                    row = preventable_lookup.get(f"{game_id}:{pitcher_id}:{int(float(pitch_count))}")
                    if isinstance(row, dict):
                        return row
                except Exception:
                    pass
            row = preventable_lookup.get(f"{game_id}:{pitcher_id}")
            return dict(row) if isinstance(row, dict) else None

        def _signal_text(pitcher: dict[str, Any], row: dict[str, Any] | None) -> list[str]:
            signal = pitcher.get("mound_signal") if isinstance(pitcher.get("mound_signal"), dict) else {}
            decision_delta = _num((row or {}).get("decisionDelta") or signal.get("decision_delta"))
            run_exposure = _num((row or {}).get("projectedPreventableRuns") or (row or {}).get("modelImpliedRunsSaved"))
            damage = (
                _num((row or {}).get("projectedDamageProbability"))
                or _num((row or {}).get("damageProbability"))
                or _num(signal.get("projected_damage_probability"))
                or _num(signal.get("damage_probability"))
            )
            reliever = (
                (row or {}).get("recommendedRelieverName")
                or ((signal.get("top_candidate") if isinstance(signal.get("top_candidate"), dict) else {}) or {}).get("player_name")
                or ((signal.get("top_candidate") if isinstance(signal.get("top_candidate"), dict) else {}) or {}).get("pitcher_name")
                or "Relief option pending"
            )
            status = "Pull Now" if pitcher.get("first_pull_now_inning") is not None else str(pitcher.get("first_alert_status") or "No Action").replace("_", " ").title()
            inning = (row or {}).get("inning") or pitcher.get("first_pull_now_inning") or pitcher.get("first_alert_inning") or "-"
            pitch_count = (row or {}).get("pitchCount") or pitcher.get("first_pull_now_pitch_count") or pitcher.get("first_alert_pitch_count") or "-"
            runs_after = (row or {}).get("runsAfterModelWindow")
            if runs_after is None:
                runs_after = pitcher.get("runs_allowed_after_signal")
            actual = "Removal unavailable"
            if pitcher.get("actual_exit_inning") is not None:
                actual = f"Removed inning {pitcher.get('actual_exit_inning')}, pitch {pitcher.get('actual_exit_pitch_count') or '-'}"
            contributors = []
            for item in ((row or {}).get("topFeatureContributions") or [])[:4]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("feature") or "").replace("_", " ").title()
                contributors.append(f"{label} ({_fmt_pct(item.get('percentile'))})")
            lines = [
                f"{pitcher.get('pitcher_name') or 'Starter'} vs {opponent}",
                f"Signal: {status}, inning {inning}, pitch {pitch_count}",
                f"Relief Edge: {_fmt_signed(decision_delta)}",
                f"Run Exposure: {_fmt_num(run_exposure)}",
                f"Optimal Relief Option: {reliever}",
                f"Actual Outcome: {actual}; {runs_after if runs_after is not None else 'runs unavailable'} runs before removal",
            ]
            if damage is not None:
                lines.insert(4, f"Damage Risk: {_fmt_pct(damage)}")
            if contributors:
                lines.append(f"Signal Rationale: {', '.join(contributors)}")
            else:
                reasons = signal.get("top_reasons") if isinstance(signal.get("top_reasons"), list) else []
                if reasons:
                    lines.append("Signal Rationale: " + ", ".join(str(reason).replace("_", " ").title() for reason in reasons[:4]))
            return lines

        starters = [
            dict(pitcher)
            for pitcher in (recap.get("starters") or [])
            if isinstance(pitcher, dict)
            and _normalize_pitching_recap_team(pitcher.get("team")) == normalized_team
            and str(pitcher.get("role") or "").lower() != "reliever"
        ]
        relievers = [
            dict(pitcher)
            for pitcher in (recap.get("starters") or [])
            if isinstance(pitcher, dict)
            and _normalize_pitching_recap_team(pitcher.get("team")) == normalized_team
            and str(pitcher.get("role") or "").lower() == "reliever"
        ]
        text_lines = [
            f"brAIn Pitching Intelligence - {normalized_team} {'vs' if normalized_team == home_team else '@'} {opponent}",
            f"{recap.get('date') or ''}",
            f"Final: {away_team} {recap.get('final_away_score') if recap.get('final_away_score') is not None else '-'} - {home_team} {recap.get('final_home_score') if recap.get('final_home_score') is not None else '-'}",
            "",
            "Peak Decision Window",
        ]
        if starters:
            for pitcher in starters:
                row = _row_for(pitcher)
                text_lines.extend(_signal_text(pitcher, row))
                text_lines.append("")
        else:
            text_lines.extend(["No starter decision window was available for this team game.", ""])
        if relievers:
            text_lines.append("Bullpen Stress Snapshot")
            for pitcher in relievers[:8]:
                signal = pitcher.get("bullpen_signal") if isinstance(pitcher.get("bullpen_signal"), dict) else {}
                rss = signal.get("rss_display_score") if signal else pitcher.get("rss_score")
                label = str(signal.get("rss_label") if signal else pitcher.get("rss_label") or "OK").replace("_", " ").title()
                text_lines.append(f"- {pitcher.get('pitcher_name') or 'Reliever'}: {label} {_fmt_num(rss)}")
            text_lines.append("")
        if replay_url:
            text_lines.extend(["Replay:", replay_url, ""])
        text_lines.append("Model note: Relief Edge and Run Exposure are calibrated decision-window estimates, not guaranteed counterfactual runs saved.")
        return "\n".join(text_lines)

        lines = [
            f"brAIn — {normalized_team} Pitching Recap",
            f"{recap.get('away_team') or ''} @ {recap.get('home_team') or ''} · {recap.get('date') or ''}",
            f"Final: {recap.get('away_team') or ''} {recap.get('final_away_score') if recap.get('final_away_score') is not None else '—'} · {recap.get('home_team') or ''} {recap.get('final_home_score') if recap.get('final_home_score') is not None else '—'}",
            "",
        ]
        for pitcher in recap.get("starters") or []:
            if not isinstance(pitcher, dict):
                continue
            role = str(pitcher.get("role") or "")
            signal = (
                str(pitcher.get("rss_label") or "")
                if role == "Reliever"
                else str(pitcher.get("peak_status") or "STAY").replace("_", " ")
            ).upper()
            lines.append(
                f"- {pitcher.get('pitcher_name') or 'Unknown'} ({role or 'Pitcher'}): "
                f"{pitcher.get('innings_pitched') or '—'} IP, {pitcher.get('pitch_count') or '—'} pitches, "
                f"{signal}, runs after signal {pitcher.get('runs_allowed_after_signal') if pitcher.get('runs_allowed_after_signal') is not None else '—'}"
            )
        if replay_url:
            lines.extend(["", f"Replay: {replay_url}"])
        return "\n".join(lines)

    def _pitching_recap_preventable_lookup(
        recap: dict[str, Any],
        team: str,
        *,
        league: str = DEFAULT_PITCHING_LEAGUE,
        replay_payload: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        game_id = str(recap.get("game_id") or "")
        game_date = str(recap.get("date") or "")
        try:
            season = int(game_date[:4])
        except Exception:
            season = date.today().year
        normalized_team = _normalize_pitching_recap_team(team) or str(team or "").upper()
        lookup: dict[str, dict[str, Any]] = {}

        def _put_row(row: dict[str, Any]) -> None:
            if not isinstance(row, dict):
                return
            row_game_id = str(row.get("gameId") or row.get("game_id") or "")
            if game_id and row_game_id and row_game_id != game_id:
                return
            pitcher_id = str(row.get("pitcherId") or row.get("pitcher_id") or "")
            if not row_game_id or not pitcher_id:
                return
            pitch_count = row.get("pitchCount")
            if pitch_count is not None:
                try:
                    lookup[f"{row_game_id}:{pitcher_id}:{int(float(pitch_count))}"] = row
                except Exception:
                    pass
            current = lookup.get(f"{row_game_id}:{pitcher_id}")
            current_runs = (
                float(current.get("projectedPreventableRuns") or 0.0)
                if isinstance(current, dict)
                else float("-inf")
            )
            row_runs = float(row.get("projectedPreventableRuns") or 0.0)
            if current is None or row_runs > current_runs:
                lookup[f"{row_game_id}:{pitcher_id}"] = row

        payload = _pitching_store_get(_pitching_preventable_model_latest_key(season=season))
        if isinstance(payload, dict):
            opportunities = payload.get("opportunities") if isinstance(payload.get("opportunities"), dict) else {}
            rows = list(((opportunities.get("teamTop") or {}).get(normalized_team) or []))
            if not rows:
                rows = list(opportunities.get("globalTop") or [])
            for row in rows:
                _put_row(row)

        # The stored preventable-runs artifact intentionally keeps only the top
        # opportunities. A recap for a normal game can still need a run-saving
        # estimate, so score matching audit windows directly from the current
        # replay/audit artifacts before declaring the field unavailable.
        try:
            audit = _pitching_audit_payload(league=league)
        except Exception:
            audit = {}
        all_windows = [
            dict(window)
            for window in (audit.get("decision_windows_all") or [])
            if isinstance(window, dict)
            and (not game_id or str(window.get("game_id") or "") == game_id)
            and (
                not normalized_team
                or str(window.get("decision_team") or "").upper() == normalized_team
                or str(window.get("opponent_team") or "").upper() == normalized_team
                or normalized_team in str(window.get("matchup") or "").upper().replace(" ", "")
            )
        ]
        if all_windows:
            try:
                season_windows = [
                    dict(window)
                    for window in (audit.get("decision_windows_all") or [])
                    if isinstance(window, dict)
                    and str(window.get("date") or "").startswith(str(season))
                ]
                calibration = _enterprise_build_runs_saved_calibration(season_windows or all_windows)
            except Exception:
                calibration = {}
            for window in all_windows:
                starter = window.get("starter") if isinstance(window.get("starter"), dict) else {}
                pitcher_id = str((starter or {}).get("pitcher_id") or "")
                if not pitcher_id:
                    continue
                try:
                    matched_entry = _enterprise_replay_entry_for_window(window, replay_payload)
                    matched_snapshot = _coerce_dict((matched_entry or {}).get("snapshot"))
                    top_candidate = _coerce_dict(window.get("top_candidate"))
                    actual_change = _enterprise_actual_change_details(window, matched_entry, replay_payload)
                    components = _enterprise_projected_runs_components(window, matched_entry)
                    scored = _enterprise_apply_runs_saved_calibration(window, components, calibration)
                    pitch_count = (
                        _enterprise_entry_pitch_count(matched_entry)
                        if isinstance(matched_entry, dict)
                        else _enterprise_int((starter or {}).get("pitch_count_in_game"))
                    )
                    component_contributions = _coerce_dict((starter or {}).get("component_contributions"))
                    top_contributions = [
                        {"feature": key, "contribution": value, "value": value}
                        for key, value in sorted(
                            component_contributions.items(),
                            key=lambda item: abs(_enterprise_number(item[1], digits=6) or 0.0),
                            reverse=True,
                        )[:4]
                    ]
                    row = {
                        "gameId": str(window.get("game_id") or game_id),
                        "gameDate": str(window.get("date") or game_date),
                        "fieldingTeam": str(window.get("decision_team") or normalized_team),
                        "battingTeam": str(window.get("opponent_team") or ""),
                        "pitcherId": pitcher_id,
                        "pitcherName": str((starter or {}).get("pitcher_name") or ""),
                        "inning": _enterprise_int(window.get("inning")),
                        "half": str(window.get("half") or ""),
                        "outs": _enterprise_int(window.get("outs")),
                        "baseState": str(window.get("base_state") or ""),
                        "pitchCount": pitch_count,
                        "currentHomeScore": _enterprise_int(matched_snapshot.get("home_score")),
                        "currentAwayScore": _enterprise_int(matched_snapshot.get("away_score")),
                        "timesThroughOrder": _enterprise_int((starter or {}).get("times_through_order")),
                        "leverageIndex": _enterprise_number(window.get("leverage_index"), digits=4),
                        "recommendationStatus": str(window.get("status") or ""),
                        "productionDegradation": _enterprise_number((starter or {}).get("degradation_score"), digits=4),
                        "normalizedDegradation": _enterprise_number((starter or {}).get("normalized_degradation_score"), digits=4),
                        "recommendedRelieverId": str(top_candidate.get("player_id") or ""),
                        "recommendedRelieverName": str(top_candidate.get("player_name") or ""),
                        "starterValueNextWindow": components.get("starterValueNextWindow"),
                        "bestRelieverValueNextWindow": components.get("alternativeValueNextWindow"),
                        "decisionDelta": _enterprise_number(window.get("decision_delta"), digits=4),
                        "projectedPreventableRuns": _enterprise_number(scored.get("projectedRunsSaved"), digits=6),
                        "modelImpliedRunsSaved": _enterprise_number(scored.get("modelImpliedRunsSaved"), digits=6),
                        "projectedDamageProbability": _enterprise_number(window.get("damage_probability"), digits=6),
                        "actualChangeInning": actual_change.get("actualChangeInning"),
                        "actualChangePitchCount": actual_change.get("actualChangePitchCount"),
                        "actualReplacementPitcher": actual_change.get("actualReplacementPitcher"),
                        "actualReplacementPitcherId": actual_change.get("actualReplacementPitcherId"),
                        "runsAfterModelWindow": actual_change.get("runsAfterModelWindow"),
                        "calibrationBucket": scored.get("calibrationBucket"),
                        "calibrationSampleCount": _enterprise_int(scored.get("calibrationSampleCount")),
                        "calibrationSource": scored.get("calibrationSource"),
                        "topFeatureContributions": top_contributions,
                    }
                    _put_row(row)
                except Exception:
                    continue
        return lookup

    def _build_pitching_recap_email_result(
        *,
        game_id: str,
        team: str,
        league: str,
        recipient_override: str | None = None,
        send: bool = False,
    ) -> dict[str, Any]:
        normalized_league = _normalize_pitching_league(league)
        normalized_team = _normalize_pitching_recap_team(team)
        if not normalized_team:
            raise HTTPException(status_code=422, detail="A valid team is required")

        replay_payload = _get_pitching_replay(str(game_id), league=normalized_league)
        if replay_payload is None:
            raise HTTPException(status_code=404, detail=f"No replay data for game {game_id}")

        full_recap = _build_game_recap(replay_payload, league=normalized_league)
        scoped_recap = _filter_pitching_recap_to_team(full_recap, normalized_team)
        starters = scoped_recap.get("starters") or []
        if not starters:
            raise HTTPException(status_code=422, detail=f"No pitching staff data available for team {normalized_team} in game {game_id}")

        email_settings = _shared_pitcher_intel_email_settings()
        settings_payload = _get_pitching_recap_settings(league=normalized_league)
        configured_recipients = settings_payload.get("team_recipients", {}).get(normalized_team, [])
        if not configured_recipients:
            configured_recipients = (email_settings.get("team_recipients") or {}).get(normalized_team, [])
        recipients = _normalize_recipients([recipient_override] if recipient_override else configured_recipients)
        delivery_error = _pitching_recap_email_delivery_error(email_settings)

        subject = _pitching_recap_email_subject(scoped_recap, normalized_team)
        preventable_lookup = _pitching_recap_preventable_lookup(
            scoped_recap,
            normalized_team,
            league=normalized_league,
            replay_payload=replay_payload,
        )
        replay_query = urlencode({"workflow": "audit", "team": normalized_team, "gameId": str(game_id)})
        preview_replay_url = f"{RUN_PREVENTION_APP_BASE_URL}{'&' if '?' in RUN_PREVENTION_APP_BASE_URL else '?'}{replay_query}"
        preview_html = _pitching_recap_email_html(
            scoped_recap,
            normalized_team,
            replay_url=preview_replay_url,
            replay_payload=replay_payload,
            preventable_lookup=preventable_lookup,
        )
        preview_text = _pitching_recap_email_text(
            scoped_recap,
            normalized_team,
            replay_url=preview_replay_url,
            replay_payload=replay_payload,
            preventable_lookup=preventable_lookup,
        )
        result: dict[str, Any] = {
            "league": normalized_league,
            "team": normalized_team,
            "game_id": str(game_id),
            "subject": subject,
            "recap": scoped_recap,
            "html": preview_html,
            "text": preview_text,
            "sent": False,
            "sent_to": [],
            "failed_recipients": [],
            "recipients": recipients,
        }
        if not send:
            return result
        if not recipients:
            raise HTTPException(status_code=422, detail=f"No recipients configured for {normalized_team}")
        if delivery_error:
            raise HTTPException(status_code=409, detail=delivery_error)

        sent_to: list[str] = []
        failed_recipients: list[str] = []
        for recipient in recipients:
            grant = issue_pitching_replay_share_grant(
                recipient_email=recipient,
                game_id=str(game_id),
                team=normalized_team,
                game_date=str(full_recap.get("date") or "") or None,
                home_team=str(full_recap.get("home_team") or "") or None,
                away_team=str(full_recap.get("away_team") or "") or None,
                source="pitching_recap_email",
            )
            replay_url = build_pitching_replay_share_url(str(grant.get("grant_id") or ""), BRAIN_APP_BASE_URL)
            html = _pitching_recap_email_html(
                scoped_recap,
                normalized_team,
                replay_url=replay_url,
                replay_payload=replay_payload,
                preventable_lookup=preventable_lookup,
            )
            text = _pitching_recap_email_text(
                scoped_recap,
                normalized_team,
                replay_url=replay_url,
                replay_payload=replay_payload,
                preventable_lookup=preventable_lookup,
            )
            send_result = _send_pitching_recap_email(html, text, subject, recipient, email_settings)
            if send_result.get("ok"):
                sent_to.append(recipient)
            else:
                failed_recipients.append(recipient)
            result["html"] = html
            result["text"] = text
        result["sent"] = bool(sent_to)
        result["sent_to"] = sent_to
        result["failed_recipients"] = failed_recipients
        return result

    def _build_pitching_refresh_response(
        snapshot: dict[str, Any],
        *,
        league: str = DEFAULT_PITCHING_LEAGUE,
    ) -> dict[str, Any]:
        summary = _get_pitching_summary(league=league) or {}
        games = _get_pitching_games(league=league)
        status = str(snapshot.get("status") or "idle")
        summary_snapshot_count = summary.get("snapshot_count")
        snapshot_snapshot_count = snapshot.get("snapshot_count")
        summary_game_count = summary.get("game_count")
        snapshot_game_count = snapshot.get("game_count")
        return {
            "status": "accepted" if status == "running" else status,
            "pitching_last_refresh_status": status,
            "league": league,
            "requested_at": snapshot.get("requested_at"),
            "started_at": snapshot.get("started_at"),
            "completed_at": snapshot.get("completed_at"),
            "generated_at": summary.get("generated_at") or snapshot.get("generated_at"),
            "snapshot_count": int(summary_snapshot_count if summary_snapshot_count is not None else snapshot_snapshot_count if snapshot_snapshot_count is not None else 0),
            "game_count": int(summary_game_count if summary_game_count is not None else snapshot_game_count if snapshot_game_count is not None else len(games)),
            "start_date": snapshot.get("start_date"),
            "end_date": snapshot.get("end_date"),
            "last_error": snapshot.get("last_error"),
            "requested_window_empty": bool(snapshot.get("requested_window_empty")),
            "artifacts_preserved": bool(snapshot.get("artifacts_preserved")),
        }

    def _start_background_pitching_refresh(
        *,
        league: str = DEFAULT_PITCHING_LEAGUE,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        league = _normalize_pitching_league(league)
        existing = _load_pitching_refresh_status(league=league)
        if str(existing.get("status") or "") == "running":
            # Guard against stuck "running" state from a timed-out/killed job.
            # If started_at is more than 35 minutes ago, treat as stale and allow re-trigger.
            started_at_str = existing.get("started_at") or existing.get("requested_at") or ""
            _stale = False
            if started_at_str:
                try:
                    from datetime import datetime as _dt, timezone as _tz
                    _started = _dt.fromisoformat(started_at_str.replace("Z", "+00:00"))
                    _age_minutes = (_dt.now(_tz.utc) - _started).total_seconds() / 60
                    if _age_minutes > 35:
                        _stale = True
                        print(f"[abs-modal] pitching refresh status stale ({_age_minutes:.1f}m) — allowing re-trigger")
                except Exception:
                    pass
            if not _stale:
                return existing
        requested_at = _utc_now_iso()
        running = _default_pitching_refresh_status()
        default_start_date, default_end_date = _default_pitching_refresh_window(league=league)
        resolved_start_date = str(start_date or default_start_date or "").strip() or None
        resolved_end_date = str(end_date or default_end_date or resolved_start_date or "").strip() or None
        running.update(
            {
                "status": "running",
                "active": True,
                "requested_at": requested_at,
                "league": league,
                "start_date": resolved_start_date,
                "end_date": resolved_end_date,
            }
        )
        STATE.pitching_refresh_status[league] = running
        _persist_pitching_refresh_status(running, league=league)
        try:
            job = pitching_refresh_job.spawn(
                requested_at=requested_at,
                league=league,
                start_date=resolved_start_date,
                end_date=resolved_end_date,
            )
            print(
                "[abs-modal] enqueued pitching refresh job "
                f"call_id={getattr(job, 'object_id', 'unknown')} "
                f"league={league} source={_pitching_refresh_source_label(league=league)} "
                f"window={resolved_start_date or 'default'}..{resolved_end_date or resolved_start_date or 'default'}"
            )
        except Exception as exc:
            failed = _default_pitching_refresh_status()
            failed.update(
                {
                    "status": "failed",
                    "active": False,
                    "requested_at": requested_at,
                    "completed_at": _utc_now_iso(),
                    "last_error": str(exc),
                    "league": league,
                    "start_date": resolved_start_date,
                    "end_date": resolved_end_date,
                }
            )
            STATE.pitching_refresh_status[league] = failed
            _persist_pitching_refresh_status(failed, league=league)
            raise HTTPException(status_code=500, detail=f"Pitching refresh enqueue failed: {exc}") from exc
        return running

    def _start_background_pitcher_hook_refresh(
        *,
        seasons: str,
        starter_target: int,
        reliever_target: int,
        min_pitch_count: int | None,
    ) -> dict[str, Any]:
        existing = _load_pitcher_hook_refresh_status()
        if str(existing.get("status") or "") == "running":
            started_at_str = existing.get("started_at") or existing.get("requested_at") or ""
            stale = False
            if started_at_str:
                try:
                    started = datetime.fromisoformat(str(started_at_str).replace("Z", "+00:00"))
                    age_minutes = (datetime.now(timezone.utc) - started).total_seconds() / 60
                    if age_minutes > 120:
                        stale = True
                        print(f"[abs-modal] pitcher hook refresh status stale ({age_minutes:.1f}m) — allowing re-trigger")
                except Exception:
                    pass
            if not stale:
                return existing
        requested_at = _utc_now_iso()
        running = _default_pitcher_hook_refresh_status()
        running.update(
            {
                "status": "running",
                "active": True,
                "requested_at": requested_at,
                "started_at": requested_at,
                "seasons": list(parse_pitcher_hook_dataset_seasons(seasons)),
                "starter_target": int(starter_target),
                "reliever_target": int(reliever_target),
                "min_pitch_count": int(min_pitch_count or settings.abs_pitching_min_pitch_count),
            }
        )
        _persist_pitcher_hook_refresh_status(running)
        try:
            job = pitcher_hook_dataset_refresh_job.spawn(
                requested_at=requested_at,
                seasons=seasons,
                starter_target=starter_target,
                reliever_target=reliever_target,
                min_pitch_count=min_pitch_count,
            )
            print(
                "[abs-modal] enqueued pitcher hook dataset refresh job "
                f"call_id={getattr(job, 'object_id', 'unknown')}"
            )
        except Exception as exc:
            failed = _default_pitcher_hook_refresh_status()
            failed.update(
                {
                    "status": "failed",
                    "active": False,
                    "requested_at": requested_at,
                    "completed_at": _utc_now_iso(),
                    "seasons": list(parse_pitcher_hook_dataset_seasons(seasons)),
                    "starter_target": int(starter_target),
                    "reliever_target": int(reliever_target),
                    "min_pitch_count": int(min_pitch_count or settings.abs_pitching_min_pitch_count),
                    "last_error": str(exc),
                }
            )
            _persist_pitcher_hook_refresh_status(failed)
            raise HTTPException(status_code=500, detail=f"Pitcher hook refresh enqueue failed: {exc}") from exc
        return running

    def _start_background_pitching_support_refresh(
        *,
        seasons: str,
        game_types: str,
        timeout_seconds: float,
        upload_outputs: bool,
        chain_pitcher_hook_dataset: bool,
    ) -> dict[str, Any]:
        existing = _load_pitching_support_refresh_status()
        if str(existing.get("status") or "") == "running":
            started_at_str = existing.get("started_at") or existing.get("requested_at") or ""
            stale = False
            if started_at_str:
                try:
                    started = datetime.fromisoformat(str(started_at_str).replace("Z", "+00:00"))
                    age_minutes = (datetime.now(timezone.utc) - started).total_seconds() / 60
                    if age_minutes > 120:
                        stale = True
                        print(f"[abs-modal] pitching support refresh status stale ({age_minutes:.1f}m) — allowing re-trigger")
                except Exception:
                    pass
            if not stale:
                return existing
        requested_at = _utc_now_iso()
        running = _default_pitching_support_refresh_status()
        running.update(
            {
                "status": "running",
                "active": True,
                "requested_at": requested_at,
                "started_at": requested_at,
                "seasons": list(parse_pitching_support_seasons(seasons)),
                "game_types": list(parse_pitching_support_game_types(game_types)),
                "timeout_seconds": float(timeout_seconds),
            }
        )
        _persist_pitching_support_refresh_status(running)
        try:
            job = pitching_support_inputs_refresh_job.spawn(
                requested_at=requested_at,
                seasons=seasons,
                game_types=game_types,
                timeout_seconds=timeout_seconds,
                upload_outputs=upload_outputs,
                chain_pitcher_hook_dataset=chain_pitcher_hook_dataset,
            )
            print(
                "[abs-modal] enqueued pitching support refresh job "
                f"call_id={getattr(job, 'object_id', 'unknown')}"
            )
        except Exception as exc:
            failed = _default_pitching_support_refresh_status()
            failed.update(
                {
                    "status": "failed",
                    "active": False,
                    "requested_at": requested_at,
                    "completed_at": _utc_now_iso(),
                    "seasons": list(parse_pitching_support_seasons(seasons)),
                    "game_types": list(parse_pitching_support_game_types(game_types)),
                    "timeout_seconds": float(timeout_seconds),
                    "last_error": str(exc),
                }
            )
            _persist_pitching_support_refresh_status(failed)
            raise HTTPException(status_code=500, detail=f"Pitching support refresh enqueue failed: {exc}") from exc
        return running

    def _start_background_pitcher_fatigue_refresh(
        *,
        seasons: str,
        starter_target: int,
        reliever_target: int,
        include_starter_signal_context: bool,
        include_charts: bool,
    ) -> dict[str, Any]:
        existing = _load_pitcher_fatigue_refresh_status()
        if str(existing.get("status") or "") == "running":
            started_at_str = existing.get("started_at") or existing.get("requested_at") or ""
            stale = False
            if started_at_str:
                try:
                    started = datetime.fromisoformat(str(started_at_str).replace("Z", "+00:00"))
                    age_minutes = (datetime.now(timezone.utc) - started).total_seconds() / 60
                    if age_minutes > 180:
                        stale = True
                        print(f"[abs-modal] pitcher fatigue refresh status stale ({age_minutes:.1f}m) — allowing re-trigger")
                except Exception:
                    pass
            if not stale:
                return existing
        requested_at = _utc_now_iso()
        running = _default_pitcher_fatigue_refresh_status()
        running.update(
            {
                "status": "running",
                "active": True,
                "requested_at": requested_at,
                "started_at": requested_at,
                "seasons": list(parse_pitcher_fatigue_research_seasons(seasons)),
                "starter_target": int(starter_target),
                "reliever_target": int(reliever_target),
                "include_starter_signal_context": bool(include_starter_signal_context),
            }
        )
        _persist_pitcher_fatigue_refresh_status(running)
        try:
            job = pitcher_fatigue_research_refresh_job.spawn(
                requested_at=requested_at,
                seasons=seasons,
                starter_target=starter_target,
                reliever_target=reliever_target,
                include_starter_signal_context=include_starter_signal_context,
                include_charts=include_charts,
            )
            print(
                "[abs-modal] enqueued pitcher fatigue research refresh job "
                f"call_id={getattr(job, 'object_id', 'unknown')}"
            )
        except Exception as exc:
            failed = _default_pitcher_fatigue_refresh_status()
            failed.update(
                {
                    "status": "failed",
                    "active": False,
                    "requested_at": requested_at,
                    "completed_at": _utc_now_iso(),
                    "seasons": list(parse_pitcher_fatigue_research_seasons(seasons)),
                    "starter_target": int(starter_target),
                    "reliever_target": int(reliever_target),
                    "include_starter_signal_context": bool(include_starter_signal_context),
                    "last_error": str(exc),
                }
            )
            _persist_pitcher_fatigue_refresh_status(failed)
            raise HTTPException(status_code=500, detail=f"Pitcher fatigue refresh enqueue failed: {exc}") from exc
        return running

    def _pitching_summary_payload(*, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any]:
        summary = _get_pitching_summary(league=league)
        if summary is not None:
            return summary
        status = _load_pitching_refresh_status(league=league)
        if str(status.get("status") or "") == "running":
            raise HTTPException(
                status_code=503,
                detail="Pitching summary is being prepared. Retry after the refresh completes.",
            )
        raise HTTPException(
            status_code=503,
            detail="Pitching summary unavailable. Run /v1/pitching/refresh first.",
        )

    def _pitching_audit_payload(*, league: str = DEFAULT_PITCHING_LEAGUE) -> dict[str, Any]:
        _pitching_summary_payload(league=league)
        audit = _get_pitching_audit(league=league)
        if audit is not None:
            return audit
        raise HTTPException(
            status_code=503,
            detail="Pitching audit unavailable even though a summary exists. Run /v1/pitching/refresh again.",
        )

    def _enterprise_number(value: Any, *, digits: int = 4) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number != number or abs(number) == float("inf"):
            return None
        return round(number, digits)

    def _enterprise_first_number(*values: Any, digits: int = 4) -> float | None:
        for value in values:
            number = _enterprise_number(value, digits=digits)
            if number is not None:
                return number
        return None

    def _enterprise_int(value: Any) -> int | None:
        number = _enterprise_number(value, digits=0)
        return int(number) if number is not None else None

    def _enterprise_text(value: Any, fallback: str = "") -> str:
        text = str(value or "").strip()
        return text or fallback

    def _enterprise_clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _enterprise_mean(values: list[float]) -> float | None:
        clean = [float(value) for value in values if _enterprise_number(value) is not None]
        if not clean:
            return None
        return sum(clean) / float(len(clean))

    def _enterprise_pitch_count(snapshot: dict[str, Any], state: dict[str, Any]) -> int | None:
        return _enterprise_int(
            state.get("official_pitch_count_in_game")
            or state.get("pitch_count_in_game")
            or snapshot.get("pitch_count")
            or state.get("replay_pitch_count_in_game")
        )

    def _enterprise_stuff_score_from_degradation(degradation_score: Any) -> float | None:
        degradation = _enterprise_number(degradation_score, digits=6)
        if degradation is None:
            return None
        # Convert the existing degradation model to a 0-100 club-facing stuff scale.
        # This keeps all current degradation inputs in the signal while making the
        # trajectory easier for a front office user to interpret.
        return round(_enterprise_clamp(100.0 - (22.0 * degradation), 20.0, 100.0), 1)

    def _enterprise_replay_entry_for_window(
        window: dict[str, Any],
        replay_payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(replay_payload, dict):
            return None
        entries = [entry for entry in replay_payload.get("entries") or [] if isinstance(entry, dict)]
        if not entries:
            return None
        target_pitch_ids = {
            _enterprise_text(window.get("pitch_id")),
            _enterprise_text(window.get("first_pull_now_pitch_id")),
            _enterprise_text(window.get("first_prep_pitch_id")),
            _enterprise_text(window.get("first_watch_pitch_id")),
            _enterprise_text(window.get("start_pitch_id")),
            _enterprise_text(window.get("end_pitch_id")),
        }
        target_pitch_ids.discard("")
        for entry in entries:
            snapshot = _coerce_dict(entry.get("snapshot"))
            if _enterprise_text(snapshot.get("pitch_id")) in target_pitch_ids:
                return entry
        pitcher_id = _enterprise_text(_coerce_dict(window.get("starter")).get("pitcher_id"))
        target_count = _enterprise_int(_coerce_dict(window.get("starter")).get("pitch_count_in_game"))
        if not pitcher_id or target_count is None:
            return None
        best_entry: dict[str, Any] | None = None
        best_distance: int | None = None
        for entry in entries:
            snapshot = _coerce_dict(entry.get("snapshot"))
            state = _coerce_dict(snapshot.get("starter_state"))
            if _enterprise_text(snapshot.get("pitcher_id")) != pitcher_id:
                continue
            pitch_count = _enterprise_pitch_count(snapshot, state)
            if pitch_count is None:
                continue
            distance = abs(int(pitch_count) - int(target_count))
            if best_distance is None or distance < best_distance:
                best_entry = entry
                best_distance = distance
        return best_entry

    def _enterprise_pitcher_timeline(
        window: dict[str, Any],
        replay_payload: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(replay_payload, dict):
            return []
        pitcher_id = _enterprise_text(_coerce_dict(window.get("starter")).get("pitcher_id"))
        target_pitch_id = _enterprise_text(window.get("pitch_id")) or _enterprise_text(window.get("end_pitch_id"))
        if not pitcher_id:
            return []
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in replay_payload.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            snapshot = _coerce_dict(entry.get("snapshot"))
            state = _coerce_dict(snapshot.get("starter_state"))
            if _enterprise_text(snapshot.get("pitcher_id")) != pitcher_id:
                continue
            pitch_id = _enterprise_text(snapshot.get("pitch_id"))
            pitch_count = _enterprise_pitch_count(snapshot, state)
            degradation = _enterprise_number(state.get("degradation_score"), digits=6)
            stuff_score = _enterprise_stuff_score_from_degradation(degradation)
            if pitch_count is None or degradation is None or stuff_score is None:
                continue
            key = pitch_id or f"{pitch_count}:{len(rows)}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "pitch_id": pitch_id,
                    "pitch_count": int(pitch_count),
                    "inning": _enterprise_int(snapshot.get("inning")),
                    "degradation": float(degradation),
                    "stuff_score": float(stuff_score),
                }
            )
            if target_pitch_id and pitch_id == target_pitch_id:
                break
        rows.sort(key=lambda item: int(item.get("pitch_count") or 0))
        return rows

    def _enterprise_trajectory_metrics(
        window: dict[str, Any],
        replay_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        timeline = _enterprise_pitcher_timeline(window, replay_payload)
        if len(timeline) < 3:
            return {
                "trajectoryLabel": "Pending",
                "trajectoryIndex": None,
                "trajectoryConfidence": None,
                "decayVelocity": None,
                "decayAcceleration": None,
                "recoveryIndex": None,
                "cliffProbability": None,
                "stuffCurve": [],
            }

        pitch_counts = [int(item["pitch_count"]) for item in timeline]
        scores = [float(item["stuff_score"]) for item in timeline]
        degradations = [float(item["degradation"]) for item in timeline]
        span = max(1, pitch_counts[-1] - pitch_counts[0])
        slope_per_10 = ((scores[-1] - scores[0]) / float(span)) * 10.0
        midpoint = max(1, len(scores) // 2)
        early_span = max(1, pitch_counts[midpoint - 1] - pitch_counts[0])
        late_span = max(1, pitch_counts[-1] - pitch_counts[midpoint])
        early_slope = ((scores[midpoint - 1] - scores[0]) / float(early_span)) * 10.0
        late_slope = ((scores[-1] - scores[midpoint]) / float(late_span)) * 10.0
        decay_velocity = max(0.0, -slope_per_10)
        decay_acceleration = late_slope - early_slope
        trough = min(scores)
        recovery_index = _enterprise_clamp((scores[-1] - trough) / max(1.0, 100.0 - trough), 0.0, 1.0)
        avg_step = _enterprise_mean([abs(scores[i] - scores[i - 1]) for i in range(1, len(scores))]) or 0.0
        max_degradation = max(degradations)
        leverage = _enterprise_number(window.get("leverage_index"), digits=4) or 1.0
        cliff_probability = _enterprise_clamp(
            0.06
            + (max_degradation * 0.11)
            + (decay_velocity * 0.05)
            + max(0.0, -decay_acceleration) * 0.035
            + max(0.0, leverage - 1.0) * 0.06
            - (recovery_index * 0.12),
            0.02,
            0.95,
        )

        if recovery_index >= 0.35 and late_slope > 0.8:
            label = "Settling/recovering"
        elif avg_step >= 12.0 and abs(slope_per_10) < 2.0:
            label = "Volatile"
        elif decay_velocity >= 4.0 or cliff_probability >= 0.65:
            label = "Rapid decay"
        elif decay_velocity >= 1.25:
            label = "Gradual fade"
        else:
            label = "Stable"

        by_inning: dict[int, list[float]] = {}
        for item in timeline:
            inning = item.get("inning")
            if isinstance(inning, int) and inning > 0:
                by_inning.setdefault(inning, []).append(float(item["stuff_score"]))
        stuff_curve = [
            round(_enterprise_mean(values) or 0.0)
            for inning, values in sorted(by_inning.items())
            if values
        ]
        if len(stuff_curve) < 2:
            sample_count = min(8, len(scores))
            if sample_count <= 1:
                stuff_curve = [round(score) for score in scores]
            else:
                stuff_curve = [
                    round(scores[round(index * (len(scores) - 1) / (sample_count - 1))])
                    for index in range(sample_count)
                ]

        confidence = _enterprise_clamp(
            0.34 + min(0.32, len(scores) / 80.0) + min(0.22, span / 120.0) - min(0.16, avg_step / 100.0),
            0.25,
            0.92,
        )
        return {
            "trajectoryLabel": label,
            "trajectoryIndex": int(round(_enterprise_clamp(slope_per_10 * 10.0, -100.0, 100.0))),
            "trajectoryConfidence": round(confidence, 3),
            "decayVelocity": round(decay_velocity, 2),
            "decayAcceleration": round(decay_acceleration, 2),
            "recoveryIndex": round(recovery_index, 3),
            "cliffProbability": round(cliff_probability, 3),
            "stuffCurve": stuff_curve,
        }

    def _enterprise_candidate_workload_rss(candidate: dict[str, Any]) -> float | None:
        explicit = _enterprise_first_number(
            candidate.get("rss_score"),
            candidate.get("reliever_stress_score"),
            candidate.get("usage_fatigue"),
            digits=4,
        )
        if explicit is not None:
            return round(_enterprise_clamp(explicit, 0.0, 1.0), 3)
        return None

    def _enterprise_candidate_workload_rss_source(candidate: dict[str, Any]) -> str:
        explicit = _enterprise_first_number(
            candidate.get("rss_score"),
            candidate.get("reliever_stress_score"),
            candidate.get("usage_fatigue"),
            digits=4,
        )
        return "explicit_candidate_rss" if explicit is not None else "unavailable"

    def _enterprise_source_status(
        *,
        value: Any = None,
        source: str,
        status: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "available": value is not None and value != "",
            "source": source,
            "status": status,
        }
        if notes:
            payload["notes"] = notes
        return payload

    def _enterprise_manager_availability(candidate: dict[str, Any]) -> dict[str, Any]:
        """Rule-based availability estimate until club day-of availability truth is attached."""
        days_rest = _enterprise_int(candidate.get("days_rest"))
        pitches_3 = _enterprise_int(candidate.get("pitches_last_3_days"))
        apps_3 = _enterprise_int(candidate.get("appearances_last_3_days"))
        usage_cost = _enterprise_number(candidate.get("usage_cost"), digits=4)
        if days_rest is None and pitches_3 is None and apps_3 is None and usage_cost is None:
            return {
                "probability": None,
                "status": "Unavailable",
                "source": "unavailable",
            }

        probability = 0.92
        if days_rest is not None:
            if days_rest <= 0:
                probability -= 0.28
            elif days_rest == 1:
                probability -= 0.08
            elif days_rest >= 3:
                probability += 0.04
        if pitches_3 is not None:
            if pitches_3 >= 45:
                probability -= 0.35
            elif pitches_3 >= 30:
                probability -= 0.24
            elif pitches_3 >= 20:
                probability -= 0.14
            elif pitches_3 >= 10:
                probability -= 0.06
        if apps_3 is not None:
            if apps_3 >= 3:
                probability -= 0.22
            elif apps_3 == 2:
                probability -= 0.12
            elif apps_3 == 1:
                probability -= 0.04
        if usage_cost is not None:
            if usage_cost >= 0.45:
                probability -= 0.15
            elif usage_cost >= 0.25:
                probability -= 0.08

        probability = round(_enterprise_clamp(probability, 0.05, 0.98), 3)
        if probability >= 0.72:
            status = "Likely available"
        elif probability >= 0.45:
            status = "Limited"
        else:
            status = "Unlikely available"
        return {
            "probability": probability,
            "status": status,
            "source": "rule_based_rest_workload_model",
        }

    def _enterprise_ip_to_float(value: Any) -> float | None:
        text = _enterprise_text(value)
        if not text:
            return None
        if "." in text:
            whole, outs = text.split(".", 1)
            try:
                return round(float(int(whole)) + (int(outs[:1] or "0") / 3.0), 3)
            except Exception:
                return None
        try:
            return round(float(text), 3)
        except Exception:
            return None

    def _enterprise_parse_game_date(value: Any) -> date | None:
        text = _enterprise_text(value)[:10]
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except Exception:
            return None

    def _enterprise_pitch_facts_for_pitcher(
        game_id: str,
        pitcher_id: str,
        *,
        league: str,
    ) -> list[dict[str, Any]]:
        if not game_id or not pitcher_id:
            return []
        try:
            payload = _load_pitching_official_pitch_facts(game_id, league=league)
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return []
        facts = _coerce_dict(payload.get("facts"))
        order = payload.get("order") if isinstance(payload.get("order"), list) else []
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for pitch_id in order:
            fact = _coerce_dict(facts.get(str(pitch_id)))
            if _enterprise_text(fact.get("pitcher_id")) != str(pitcher_id):
                continue
            sequence = _enterprise_int(fact.get("sequence_index"))
            key = f"{pitch_id}:{sequence}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(fact)
        rows.sort(key=lambda item: _enterprise_int(item.get("sequence_index")) or 0)
        return rows

    def _enterprise_postgame_report_for_game(
        game_id: str,
        *,
        league: str,
        cache: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        normalized_game_id = _enterprise_text(game_id)
        if not normalized_game_id:
            return None
        if normalized_game_id in cache:
            return cache.get(normalized_game_id) or None
        replay_payload = _enterprise_pitching_replay_for_features(normalized_game_id, league=league)
        if not isinstance(replay_payload, dict):
            cache[normalized_game_id] = {}
            return None
        try:
            report = _build_game_recap(replay_payload, league=league)
        except Exception:
            report = {}
        cache[normalized_game_id] = dict(report) if isinstance(report, dict) else {}
        return cache.get(normalized_game_id) or None

    def _enterprise_rss_signal_for_pitcher(
        game_id: str,
        pitcher_id: str,
        *,
        league: str,
        cache: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        normalized_game_id = _enterprise_text(game_id)
        normalized_pitcher_id = _enterprise_text(pitcher_id)
        if not normalized_game_id or not normalized_pitcher_id:
            return None
        if normalized_game_id in cache:
            meta = cache.get(normalized_game_id) or {}
        else:
            raw_meta = _live_signal_store_get(live_signal_game_store, normalized_game_id, {})
            meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
            cache[normalized_game_id] = meta
        pitcher_states = meta.get("pitcher_states") if isinstance(meta.get("pitcher_states"), dict) else {}
        backfill_signals = meta.get("backfill_signals") if isinstance(meta.get("backfill_signals"), dict) else {}
        state = _coerce_dict(pitcher_states.get(normalized_pitcher_id))
        signals = [
            dict(signal)
            for signal in (backfill_signals.get(normalized_pitcher_id) or [])
            if isinstance(signal, dict)
        ]
        rss_values = [
            value
            for value in [
                _enterprise_number(state.get("rss_score"), digits=4),
                *[
                    _enterprise_number(signal.get("rss_score"), digits=4)
                    for signal in signals
                ],
            ]
            if value is not None
        ]
        if not rss_values and not state and not signals:
            return None
        rss_score = round(_enterprise_clamp(max(rss_values) if rss_values else 0.0, 0.0, 1.0), 4)
        rss_label = "DISTRESS" if rss_score >= 0.50 else "WATCH" if rss_score >= 0.25 else "OK"
        first_watch = next((signal for signal in signals if float(signal.get("rss_score") or 0.0) >= 0.25), None)
        first_distress = next((signal for signal in signals if float(signal.get("rss_score") or 0.0) >= 0.50), None)
        trigger_signal = first_distress if rss_label == "DISTRESS" and isinstance(first_distress, dict) else first_watch
        trigger_level = (
            "DISTRESS"
            if trigger_signal is first_distress and isinstance(first_distress, dict)
            else "WATCH"
            if isinstance(first_watch, dict)
            else None
        )
        return {
            "rssScore": rss_score,
            "rssLabel": rss_label,
            "rssHasMeasurement": bool(state or signals),
            "rssTriggerLevel": trigger_level,
            "rssTriggerInning": _enterprise_int((trigger_signal or {}).get("inning")) if isinstance(trigger_signal, dict) else None,
            "rssTriggerPitchCount": _enterprise_int((trigger_signal or {}).get("pitch_count")) if isinstance(trigger_signal, dict) else None,
            "rssActualExitPitchCount": _enterprise_int(
                (trigger_signal or {}).get("pulled_pc") if isinstance(trigger_signal, dict) else None
            )
            or _enterprise_int(state.get("pitch_count")),
            "rssSource": "live_signal_game_store_backfill_signals",
            "sourceStatus": _enterprise_source_status(
                value=rss_score,
                source="live_signal_game_store_backfill_signals",
                status="model",
                notes="RSS is computed from stored live pitch-feed scorer state and postgame backfill signal events. No on-demand backfill is run for enterprise season views.",
            ),
        }
        return None

    def _enterprise_appearance_facts_for_games(
        games: list[dict[str, Any]],
        *,
        league: str,
        team: str | None = None,
        include_pitch_facts: bool = False,
        include_rss: bool = True,
        postgame_cache: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_team = _normalize_pitching_recap_team(team) or _enterprise_text(team).upper()
        appearances: list[dict[str, Any]] = []
        rss_cache = postgame_cache if postgame_cache is not None else {}
        for game in games:
            if not isinstance(game, dict):
                continue
            game_id = _enterprise_text(game.get("game_id"))
            if not game_id:
                continue
            home = _enterprise_text(game.get("home_team")).upper()
            away = _enterprise_text(game.get("away_team")).upper()
            if normalized_team and normalized_team not in {home, away}:
                continue
            try:
                official_boxscore = _load_pitching_official_boxscore(game_id, league=league)
            except Exception:
                official_boxscore = {}
            if not official_boxscore:
                continue
            for pitcher_id, official_row_raw in official_boxscore.items():
                official_row = _coerce_dict(official_row_raw)
                pitcher_team = _enterprise_text(official_row.get("team")).upper()
                if normalized_team and pitcher_team != normalized_team:
                    continue
                appearance_order = _enterprise_int(official_row.get("appearance_order"))
                role = "Starter" if appearance_order == 0 else "Reliever" if appearance_order is not None else None
                pitch_rows = (
                    _enterprise_pitch_facts_for_pitcher(game_id, str(pitcher_id), league=league)
                    if include_pitch_facts
                    else []
                )
                first_pitch = pitch_rows[0] if pitch_rows else {}
                last_pitch = pitch_rows[-1] if pitch_rows else {}
                opponent = away if pitcher_team == home else home if pitcher_team == away else ""
                official_ip = _enterprise_ip_to_float(official_row.get("ip"))
                official_np = _enterprise_int(official_row.get("np"))
                rss_signal = (
                    _enterprise_rss_signal_for_pitcher(
                        game_id,
                        str(pitcher_id),
                        league=league,
                        cache=rss_cache,
                    )
                    if include_rss and role == "Reliever"
                    else None
                )
                source_status = {
                    "role": _enterprise_source_status(
                        value=role,
                        source="statsapi_official_boxscore_pitching_order",
                        status="available" if role else "unavailable",
                        notes="Starter/reliever appearance role is derived strictly from official pitching appearance order.",
                    ),
                    "officialLine": _enterprise_source_status(
                        value=official_row.get("ip"),
                        source="statsapi_official_boxscore",
                        status="available" if official_row.get("ip") is not None else "unavailable",
                    ),
                    "pitchFacts": _enterprise_source_status(
                        value=last_pitch.get("pitch_count") if pitch_rows else None,
                        source="statsapi_live_game_feed_pitch_facts",
                        status="available" if pitch_rows else "unavailable",
                        notes="Entry/exit pitch facts require the official live feed pitch sequence.",
                    ),
                    "rss": (
                        dict(rss_signal.get("sourceStatus"))
                        if isinstance(rss_signal, dict) and isinstance(rss_signal.get("sourceStatus"), dict)
                        else _enterprise_source_status(
                            value=None,
                            source="pitching_postgame_bullpen_signal",
                            status="unavailable",
                            notes="No finalized reliever RSS signal found for this appearance.",
                        )
                    ),
                }
                appearances.append(
                    {
                        "id": f"{game_id}:{pitcher_id}",
                        "gameId": game_id,
                        "date": _enterprise_text(game.get("date")),
                        "matchup": _enterprise_text(game.get("matchup"), f"{away} @ {home}".strip(" @")),
                        "team": pitcher_team,
                        "opponent": opponent,
                        "pitcherId": str(pitcher_id),
                        "pitcher": _enterprise_text(official_row.get("name"), str(pitcher_id)),
                        "role": role,
                        "roleSource": "statsapi_official_boxscore_pitching_order" if role else "unavailable",
                        "roleStatus": "available" if role else "unavailable",
                        "teamAppearanceOrder": appearance_order + 1 if appearance_order is not None else None,
                        "officialInningsPitchedText": _enterprise_text(official_row.get("ip")) or None,
                        "officialInningsPitched": official_ip,
                        "officialPitchCount": official_np,
                        "earnedRuns": _enterprise_int(official_row.get("er")),
                        "runs": _enterprise_int(official_row.get("r")),
                        "hits": _enterprise_int(official_row.get("h")),
                        "walks": _enterprise_int(official_row.get("bb")),
                        "strikeouts": _enterprise_int(official_row.get("so")),
                        "homeRuns": _enterprise_int(official_row.get("hr")),
                        "entryInning": _enterprise_int(first_pitch.get("inning")),
                        "exitInning": _enterprise_int(last_pitch.get("inning")),
                        "entryPitchCount": _enterprise_int(first_pitch.get("pitch_count")),
                        "exitPitchCount": _enterprise_int(last_pitch.get("pitch_count")) or official_np,
                        "entryOpponentRuns": _enterprise_int(first_pitch.get("current_opponent_runs")),
                        "exitOpponentRuns": _enterprise_int(last_pitch.get("current_opponent_runs")),
                        "entrySequenceIndex": _enterprise_int(first_pitch.get("sequence_index")),
                        "exitSequenceIndex": _enterprise_int(last_pitch.get("sequence_index")),
                        "rssScore": rss_signal.get("rssScore") if isinstance(rss_signal, dict) else None,
                        "rssLabel": rss_signal.get("rssLabel") if isinstance(rss_signal, dict) else None,
                        "rssHasMeasurement": rss_signal.get("rssHasMeasurement") if isinstance(rss_signal, dict) else False,
                        "rssTriggerLevel": rss_signal.get("rssTriggerLevel") if isinstance(rss_signal, dict) else None,
                        "rssTriggerInning": rss_signal.get("rssTriggerInning") if isinstance(rss_signal, dict) else None,
                        "rssTriggerPitchCount": rss_signal.get("rssTriggerPitchCount") if isinstance(rss_signal, dict) else None,
                        "rssActualExitPitchCount": rss_signal.get("rssActualExitPitchCount") if isinstance(rss_signal, dict) else None,
                        "rssSource": rss_signal.get("rssSource") if isinstance(rss_signal, dict) else "unavailable",
                        "sourceStatus": source_status,
                    }
                )
        appearances.sort(
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("gameId") or ""),
                int(item.get("teamAppearanceOrder") or 999),
                str(item.get("pitcherId") or ""),
            )
        )
        return appearances

    def _enterprise_reliever_workload_facts(
        appearances: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_pitcher: dict[str, list[dict[str, Any]]] = {}
        for appearance in appearances:
            pitcher_id = _enterprise_text(appearance.get("pitcherId"))
            if not pitcher_id:
                continue
            by_pitcher.setdefault(pitcher_id, []).append(appearance)

        workload_rows: list[dict[str, Any]] = []
        for pitcher_id, pitcher_appearances in by_pitcher.items():
            pitcher_appearances.sort(
                key=lambda item: (
                    str(item.get("date") or ""),
                    str(item.get("gameId") or ""),
                    int(item.get("teamAppearanceOrder") or 999),
                )
            )
            prior: list[dict[str, Any]] = []
            for appearance in pitcher_appearances:
                if _enterprise_text(appearance.get("role")) != "Reliever":
                    prior.append(appearance)
                    continue
                current_date = _enterprise_parse_game_date(appearance.get("date"))
                prior_with_dates = [
                    row
                    for row in prior
                    if _enterprise_parse_game_date(row.get("date")) is not None
                ]
                previous = prior_with_dates[-1] if prior_with_dates else None
                days_rest = None
                if current_date is not None and previous is not None:
                    previous_date = _enterprise_parse_game_date(previous.get("date"))
                    if previous_date is not None:
                        days_rest = max(0, (current_date - previous_date).days)
                recent_rows: list[dict[str, Any]] = []
                if current_date is not None:
                    for row in prior_with_dates:
                        row_date = _enterprise_parse_game_date(row.get("date"))
                        if row_date is None:
                            continue
                        day_gap = (current_date - row_date).days
                        if 0 <= day_gap <= 3:
                            recent_rows.append(row)
                pitches_last_3 = sum(int(row.get("officialPitchCount") or 0) for row in recent_rows)
                innings_last_3 = sum(float(row.get("officialInningsPitched") or 0.0) for row in recent_rows)
                back_to_back = bool(days_rest is not None and days_rest <= 1 and previous is not None)
                manager_candidate = {
                    "days_rest": days_rest,
                    "pitches_last_3_days": pitches_last_3,
                    "appearances_last_3_days": len(recent_rows),
                }
                manager_availability = _enterprise_manager_availability(manager_candidate)
                workload_row = {
                    "id": appearance.get("id"),
                    "gameId": appearance.get("gameId"),
                    "date": appearance.get("date"),
                    "team": appearance.get("team"),
                    "pitcherId": pitcher_id,
                    "pitcher": appearance.get("pitcher"),
                    "daysRestBeforeAppearance": days_rest,
                    "pitchesLast3Days": int(pitches_last_3),
                    "appearancesLast3Days": len(recent_rows),
                    "inningsLast3Days": round(innings_last_3, 3),
                    "backToBack": back_to_back,
                    "multiInningRelief": bool((appearance.get("officialInningsPitched") or 0) >= 2.0),
                    "managerAvailabilityProbability": manager_availability.get("probability"),
                    "managerAvailabilityStatus": manager_availability.get("status"),
                    "managerAvailabilitySource": manager_availability.get("source"),
                    "workloadSource": "statsapi_official_boxscore_appearance_history",
                    "sourceStatus": {
                        "workload": _enterprise_source_status(
                            value=True,
                            source="statsapi_official_boxscore_appearance_history",
                            status="available",
                            notes="Recent workload is computed from official pitching lines before this appearance.",
                        ),
                        "managerAvailability": _enterprise_source_status(
                            value=manager_availability.get("probability"),
                            source=str(manager_availability.get("source") or "unavailable"),
                            status="model" if manager_availability.get("probability") is not None else "unavailable",
                            notes="Rule-based estimate until club day-of availability is attached.",
                        ),
                    },
                }
                workload_rows.append(workload_row)
                prior.append(appearance)
        workload_rows.sort(
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("gameId") or ""),
                str(item.get("pitcherId") or ""),
            )
        )
        return workload_rows

    def _enterprise_workload_summary_from_game_log(game_log: list[dict[str, Any]]) -> dict[str, Any]:
        relief_games = [row for row in game_log if _enterprise_text(row.get("role")) == "Reliever"]
        if not relief_games:
            return {
                "reliefAppearances": 0,
                "multiInningReliefAppearances": 0,
                "backToBackAppearances": 0,
                "avgReliefInnings": None,
                "avgReliefPitches": None,
                "avgDaysRest": None,
                "avgPitchesLast3Days": None,
                "maxPitchesLast3Days": None,
                "workloadSource": "unavailable",
            }
        days_rest_values = [
            int(row["daysRestBeforeAppearance"])
            for row in relief_games
            if row.get("daysRestBeforeAppearance") is not None
        ]
        pitches_last_3 = [
            int(row["pitchesLast3Days"])
            for row in relief_games
            if row.get("pitchesLast3Days") is not None
        ]
        return {
            "reliefAppearances": len(relief_games),
            "multiInningReliefAppearances": sum(1 for row in relief_games if row.get("multiInningRelief")),
            "backToBackAppearances": sum(1 for row in relief_games if row.get("backToBack")),
            "avgReliefInnings": _enterprise_number(
                _enterprise_mean([float(row.get("officialInningsPitched") or 0.0) for row in relief_games]),
                digits=3,
            ),
            "avgReliefPitches": _enterprise_number(
                _enterprise_mean([float(row.get("officialPitchCount") or 0.0) for row in relief_games]),
                digits=1,
            ),
            "avgDaysRest": _enterprise_number(_enterprise_mean([float(value) for value in days_rest_values]), digits=2),
            "avgPitchesLast3Days": _enterprise_number(
                _enterprise_mean([float(value) for value in pitches_last_3]),
                digits=1,
            ),
            "maxPitchesLast3Days": max(pitches_last_3) if pitches_last_3 else None,
            "workloadSource": "statsapi_official_boxscore_appearance_history",
        }

    def _enterprise_projected_runs_components(
        window: dict[str, Any],
        entry: dict[str, Any] | None,
    ) -> dict[str, Any]:
        recommendation = _coerce_dict(entry.get("recommendation") if isinstance(entry, dict) else None)
        top_candidate = _coerce_dict(window.get("top_candidate"))
        starter_value = _enterprise_number(recommendation.get("starter_value_next_3_hitters"), digits=4)
        alternative_value = _enterprise_number(recommendation.get("best_reliever_value_next_3_hitters"), digits=4)
        if alternative_value is None:
            alternative_value = _enterprise_number(top_candidate.get("net_option_score"), digits=4)
        decision_delta = _enterprise_first_number(
            recommendation.get("decision_delta"),
            window.get("decision_delta"),
            digits=4,
        )
        if starter_value is not None and alternative_value is not None:
            model_delta = alternative_value - starter_value
        else:
            model_delta = decision_delta or 0.0
        wp_delta = abs(
            _enterprise_first_number(
                recommendation.get("estimated_win_probability_delta"),
                window.get("estimated_win_probability_delta"),
                window.get("directional_wp_opportunity"),
                digits=6,
            )
            or 0.0
        )
        leverage = _enterprise_clamp(_enterprise_number(window.get("leverage_index"), digits=4) or 1.0, 0.6, 2.5)
        runs_from_model = float(model_delta) * 0.12
        runs_from_wp = wp_delta / max(0.08, 0.18 * leverage) if wp_delta > 0 else 0.0
        if wp_delta > 0 and model_delta > 0:
            projected = (runs_from_model * 0.7) + (runs_from_wp * 0.3)
        else:
            projected = runs_from_model
        status = _enterprise_text(window.get("status")).upper()
        flags = _coerce_dict(window.get("flags"))
        if status in {"PULL_NOW", "PREP", "WATCH"} and not flags.get("bullpen_thin_stay"):
            projected = max(0.0, projected)
        elif flags.get("bullpen_thin_stay"):
            projected = min(0.0, projected)
        usage_cost = _enterprise_number(top_candidate.get("usage_cost"), digits=4)
        projected_runs = round(_enterprise_clamp(projected, -1.5, 1.75), 3)
        return {
            "starterValueNextWindow": starter_value,
            "alternativeValueNextWindow": alternative_value,
            "starterRunsNextWindow": round(max(0.0, -(starter_value or 0.0) * 0.12), 3) if starter_value is not None else None,
            "alternativeRunsNextWindow": round(max(0.0, -(alternative_value or 0.0) * 0.12), 3) if alternative_value is not None else None,
            "transitionCost": usage_cost,
            "bullpenUsageCost": usage_cost,
            "projectedRunsSaved": projected_runs,
            "modelImpliedRunsSaved": projected_runs,
            "dollarsProtected": int(round(max(0.0, projected_runs) * 800000.0)) if projected_runs > 0 else 0,
        }

    def _enterprise_degradation_band(value: Any) -> str:
        number = _enterprise_number(value, digits=4)
        if number is None:
            return "deg_unknown"
        if number < 0.75:
            return "deg_low"
        if number < 1.25:
            return "deg_medium"
        if number < 2.0:
            return "deg_high"
        return "deg_extreme"

    def _enterprise_leverage_band(value: Any) -> str:
        number = _enterprise_number(value, digits=4)
        if number is None:
            return "li_unknown"
        if number < 0.85:
            return "li_routine"
        if number < 1.5:
            return "li_elevated"
        return "li_high"

    def _enterprise_delta_band(value: Any) -> str:
        number = abs(_enterprise_number(value, digits=4) or 0.0)
        if number < 0.4:
            return "delta_small"
        if number < 1.25:
            return "delta_medium"
        if number < 2.5:
            return "delta_large"
        return "delta_extreme"

    def _enterprise_inning_band(value: Any) -> str:
        inning = _enterprise_int(value)
        if inning is None or inning <= 0:
            return "inn_unknown"
        if inning <= 3:
            return "inn_early"
        if inning <= 6:
            return "inn_middle"
        return "inn_late"

    def _enterprise_calibration_keys(window: dict[str, Any]) -> list[str]:
        starter = _coerce_dict(window.get("starter"))
        status = _enterprise_text(window.get("status"), "UNKNOWN").upper()
        degradation = _enterprise_degradation_band(starter.get("degradation_score"))
        leverage = _enterprise_leverage_band(window.get("leverage_index"))
        inning = _enterprise_inning_band(window.get("inning"))
        delta = _enterprise_delta_band(window.get("decision_delta"))
        return [
            f"{status}|{degradation}|{leverage}|{inning}|{delta}",
            f"{status}|{degradation}|{leverage}|any|{delta}",
            f"{status}|{degradation}|{leverage}|any|any",
            f"{status}|any|{leverage}|any|any",
            f"{status}|any|any|any|any",
            "global",
        ]

    def _enterprise_wp_to_runs(wp_delta: Any, leverage: Any) -> float:
        wp = abs(_enterprise_number(wp_delta, digits=6) or 0.0)
        li = _enterprise_clamp(_enterprise_number(leverage, digits=4) or 1.0, 0.6, 2.5)
        if wp <= 0:
            return 0.0
        return wp / max(0.08, 0.18 * li)

    def _enterprise_realized_runs_proxy(window: dict[str, Any], model_runs: float) -> float:
        flags = _coerce_dict(window.get("flags"))
        leverage = window.get("leverage_index")
        delay_runs = _enterprise_wp_to_runs(window.get("realized_delay_tax"), leverage)
        opportunity_runs = _enterprise_wp_to_runs(
            window.get("directional_wp_opportunity") or window.get("estimated_win_probability_delta"),
            leverage,
        )
        if flags.get("delayed_change_window"):
            return round(max(delay_runs, opportunity_runs * 0.55, max(0.0, model_runs) * 0.65), 4)
        if flags.get("missed_hook_window") or flags.get("high_leverage_holdout"):
            return round(max(delay_runs, opportunity_runs * 0.45, max(0.0, model_runs) * 0.5), 4)
        if flags.get("bullpen_thin_stay"):
            return round(min(model_runs, 0.0), 4)
        if flags.get("justified_stay_window"):
            return round(min(model_runs * 0.35, 0.05), 4)
        status = _enterprise_text(window.get("status")).upper()
        if status in {"PULL_NOW", "PREP", "WATCH"}:
            return round(max(opportunity_runs * 0.45, max(0.0, model_runs) * 0.55), 4)
        return round(model_runs, 4)

    def _enterprise_add_calibration_sample(
        buckets: dict[str, dict[str, Any]],
        key: str,
        *,
        model_runs: float,
        realized_runs: float,
    ) -> None:
        bucket = buckets.setdefault(
            key,
            {
                "sampleCount": 0,
                "modelSum": 0.0,
                "realizedSum": 0.0,
                "absModelSum": 0.0,
                "absRealizedSum": 0.0,
            },
        )
        bucket["sampleCount"] += 1
        bucket["modelSum"] += float(model_runs)
        bucket["realizedSum"] += float(realized_runs)
        bucket["absModelSum"] += abs(float(model_runs))
        bucket["absRealizedSum"] += abs(float(realized_runs))

    def _enterprise_build_runs_saved_calibration(windows: list[dict[str, Any]]) -> dict[str, Any]:
        buckets: dict[str, dict[str, Any]] = {}
        source_count = 0
        for window in windows:
            if not isinstance(window, dict):
                continue
            components = _enterprise_projected_runs_components(window, None)
            model_runs = _enterprise_number(components.get("modelImpliedRunsSaved"), digits=6)
            if model_runs is None or abs(model_runs) < 0.005:
                continue
            realized_runs = _enterprise_realized_runs_proxy(window, float(model_runs))
            for key in _enterprise_calibration_keys(window):
                _enterprise_add_calibration_sample(
                    buckets,
                    key,
                    model_runs=float(model_runs),
                    realized_runs=float(realized_runs),
                )
            source_count += 1

        public_buckets: dict[str, dict[str, Any]] = {}
        for key, bucket in buckets.items():
            sample_count = int(bucket.get("sampleCount") or 0)
            if sample_count <= 0:
                continue
            avg_model = float(bucket.get("modelSum") or 0.0) / sample_count
            avg_realized = float(bucket.get("realizedSum") or 0.0) / sample_count
            abs_model = float(bucket.get("absModelSum") or 0.0) / sample_count
            abs_realized = float(bucket.get("absRealizedSum") or 0.0) / sample_count
            raw_factor = abs_realized / max(0.04, abs_model)
            factor = round(_enterprise_clamp(raw_factor, 0.35, 1.65), 3)
            public_buckets[key] = {
                "sampleCount": sample_count,
                "avgModelRunsSaved": round(avg_model, 4),
                "avgRealizedRunsSavedProxy": round(avg_realized, 4),
                "absModelRunsSaved": round(abs_model, 4),
                "absRealizedRunsSavedProxy": round(abs_realized, 4),
                "calibrationFactor": factor,
            }
        return {
            "sourceWindowCount": source_count,
            "bucketCount": len(public_buckets),
            "minExactBucketSamples": 6,
            "buckets": public_buckets,
        }

    def _enterprise_apply_runs_saved_calibration(
        window: dict[str, Any],
        components: dict[str, Any],
        calibration: dict[str, Any] | None,
    ) -> dict[str, Any]:
        model_runs = _enterprise_number(components.get("modelImpliedRunsSaved"), digits=6)
        if model_runs is None:
            return {
                **components,
                "projectedRunsSaved": None,
                "dollarsProtected": None,
                "calibrationBucket": None,
                "calibrationSampleCount": 0,
                "calibrationFactor": None,
                "calibrationSource": "unavailable",
            }
        buckets = _coerce_dict((calibration or {}).get("buckets"))
        selected_key = None
        selected_bucket: dict[str, Any] | None = None
        for key in _enterprise_calibration_keys(window):
            bucket = _coerce_dict(buckets.get(key))
            sample_count = int(bucket.get("sampleCount") or 0)
            min_samples = 6 if key != "global" else 20
            if sample_count >= min_samples:
                selected_key = key
                selected_bucket = bucket
                break
        if selected_bucket is None:
            return {
                **components,
                "projectedRunsSaved": None,
                "dollarsProtected": None,
                "calibrationBucket": None,
                "calibrationSampleCount": 0,
                "calibrationFactor": None,
                "calibrationSource": "unavailable_insufficient_calibration_samples",
            }
        factor = _enterprise_number(selected_bucket.get("calibrationFactor"), digits=4) or 1.0
        projected = round(_enterprise_clamp(float(model_runs) * factor, -1.5, 1.75), 3)
        return {
            **components,
            "projectedRunsSaved": projected,
            "dollarsProtected": int(round(max(0.0, projected) * 800000.0)) if projected > 0 else 0,
            "calibrationBucket": selected_key,
            "calibrationSampleCount": int(selected_bucket.get("sampleCount") or 0),
            "calibrationFactor": round(float(factor), 3),
            "calibrationSource": "historical_artifact_bucket",
        }

    def _enterprise_inning_label(window: dict[str, Any]) -> str:
        inning = _enterprise_int(window.get("inning"))
        half = _enterprise_text(window.get("half")).lower()
        if inning is None:
            return "Inning pending"
        if half.startswith("top") or half in {"t", "away"}:
            return f"Top {inning}"
        if half.startswith("bot") or half in {"bottom", "b", "home"}:
            return f"Bottom {inning}"
        return f"Inning {inning}"

    def _enterprise_batter_pocket(window: dict[str, Any]) -> str:
        pocket = _coerce_dict(window.get("upcoming_pocket"))
        hitters = pocket.get("hitters") if isinstance(pocket.get("hitters"), list) else []
        names = [
            _enterprise_text(_coerce_dict(hitter).get("player_name"))
            for hitter in hitters
            if _enterprise_text(_coerce_dict(hitter).get("player_name"))
        ]
        if names:
            return " / ".join(names[:3])
        pattern = _enterprise_text(pocket.get("handedness_pattern"))
        return pattern or "Pocket data pending"

    def _enterprise_recommendation(window: dict[str, Any]) -> str:
        flags = _coerce_dict(window.get("flags"))
        status = _enterprise_text(window.get("status")).upper()
        if flags.get("bullpen_thin_stay"):
            return "Hold starter"
        if status == "PULL_NOW":
            return "Change pitcher"
        if status == "PREP":
            return "Prepare bullpen"
        if status == "WATCH":
            return "Monitor only"
        return "Hold starter"

    def _enterprise_recommendation_reason(window: dict[str, Any]) -> str:
        flags = _coerce_dict(window.get("flags"))
        starter = _coerce_dict(window.get("starter"))
        top_candidate = _coerce_dict(window.get("top_candidate"))
        status = _enterprise_text(window.get("status")).upper()
        pitcher = _enterprise_text(starter.get("pitcher_name"), "Starter")
        candidate = _enterprise_text(top_candidate.get("player_name"))
        leverage = _enterprise_number(window.get("leverage_index"), digits=2)
        degradation = _enterprise_number(starter.get("degradation_score"), digits=2)
        leverage_text = f" in {leverage:.2f} leverage" if leverage is not None else ""
        degradation_text = f" with degradation {degradation:.2f}" if degradation is not None else ""
        if flags.get("bullpen_thin_stay"):
            return (
                "Hold is currently justified by bullpen constraints; no available alternative "
                "clears the current decision threshold."
            )
        if status == "PULL_NOW":
            if candidate:
                return f"{pitcher}{degradation_text}{leverage_text}; {candidate} is the top available alternative."
            return f"{pitcher}{degradation_text}{leverage_text}; model says change, but no named alternative is attached."
        if status == "PREP":
            if candidate:
                return f"Prepare for the next pocket; {candidate} is the top available relief option."
            return "Prepare bullpen; starter degradation is rising but the adapter has no named alternative."
        if status == "WATCH":
            return "Monitor only; current degradation has not cleared the run-saving change threshold."
        return "Hold starter; the current alternative board does not clear the run-saving threshold."

    def _enterprise_window_to_decision(
        window: dict[str, Any],
        *,
        replay_payload: dict[str, Any] | None = None,
        calibration: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        starter = _coerce_dict(window.get("starter"))
        flags = _coerce_dict(window.get("flags"))
        top_reasons = window.get("top_reasons") if isinstance(window.get("top_reasons"), list) else []
        matched_entry = _enterprise_replay_entry_for_window(window, replay_payload)
        trajectory = _enterprise_trajectory_metrics(window, replay_payload)
        raw_runs_components = _enterprise_projected_runs_components(window, matched_entry)
        runs_components = _enterprise_apply_runs_saved_calibration(window, raw_runs_components, calibration)
        calibration_note = "Preventable Runs is calibrated against comparable historical artifact windows."
        if flags.get("bullpen_thin_stay"):
            calibration_note = "Preventable Runs is calibrated with bullpen-thin hold context."
        if runs_components.get("calibrationSource") != "historical_artifact_bucket":
            calibration_note = "Calibrated Preventable Runs unavailable; model-implied value is retained separately because comparable samples are insufficient."
        return {
            "id": _enterprise_text(window.get("window_id"), _enterprise_text(window.get("pitch_id"), "decision")),
            "team": _enterprise_text(window.get("decision_team"), "TBD"),
            "pitcher": _enterprise_text(starter.get("pitcher_name"), "Pitcher pending"),
            "role": "Starter",
            "opponent": _enterprise_text(window.get("opponent_team"), "TBD"),
            "inning": _enterprise_inning_label(window),
            "batterPocket": _enterprise_batter_pocket(window),
            "trajectoryLabel": trajectory["trajectoryLabel"],
            "trajectoryIndex": trajectory["trajectoryIndex"],
            "trajectoryConfidence": trajectory["trajectoryConfidence"],
            "decayVelocity": trajectory["decayVelocity"],
            "decayAcceleration": trajectory["decayAcceleration"],
            "recoveryIndex": trajectory["recoveryIndex"],
            "cliffProbability": trajectory["cliffProbability"],
            "currentDegradation": _enterprise_number(starter.get("degradation_score"), digits=3),
            "enhancedDegradation": _enterprise_number(starter.get("enhanced_degradation_score"), digits=3),
            "normalizedDegradation": _enterprise_number(starter.get("normalized_degradation_score"), digits=4),
            "normalizedComponentScores": _coerce_dict(starter.get("normalized_component_scores")),
            "normalizedComponentWeights": _coerce_dict(starter.get("normalized_component_weights")),
            "normalizedWeightedComponents": _coerce_dict(starter.get("normalized_weighted_components")),
            "normalizationSource": _enterprise_text(starter.get("normalization_source")) or None,
            "empiricalDegradationPercentile": _enterprise_number(starter.get("empirical_degradation_percentile"), digits=4),
            "empiricalDegradationSampleCount": int(starter.get("empirical_degradation_sample_count") or 0),
            "pitcherEmpiricalDegradationPercentile": _enterprise_number(starter.get("pitcher_empirical_degradation_percentile"), digits=4),
            "pitcherEmpiricalDegradationSampleCount": int(starter.get("pitcher_empirical_degradation_sample_count") or 0),
            "empiricalComponentPercentiles": _coerce_dict(starter.get("empirical_component_percentiles")),
            "empiricalPitchTypePercentiles": _coerce_dict(starter.get("empirical_pitch_type_percentiles")),
            "empiricalDistributionSource": _enterprise_text(starter.get("empirical_distribution_source")) or None,
            "arsenalVeloDecay": _enterprise_number(starter.get("arsenal_velo_decay"), digits=3),
            "arsenalSpinDecay": _enterprise_number(starter.get("arsenal_spin_decay"), digits=3),
            "opponentAdjustedWhiffDrop": _enterprise_number(starter.get("opponent_adjusted_whiff_drop"), digits=4),
            "opponentWhiffFactor": _enterprise_number(starter.get("opponent_whiff_factor"), digits=3),
            "inningDecayFactor": _enterprise_number(starter.get("inning_decay_factor"), digits=4),
            "inningDecaySource": _enterprise_text(starter.get("inning_decay_source")) or None,
            "ttoDecayFactor": _enterprise_number(starter.get("tto_decay_factor"), digits=4),
            "ttoDecaySource": _enterprise_text(starter.get("tto_decay_source")) or None,
            "strikeRateStability": _enterprise_number(starter.get("strike_rate_stability"), digits=4),
            "componentContributions": _coerce_dict(starter.get("component_contributions")),
            "pitchTypeVelocityTrends": _coerce_dict(starter.get("pitch_type_velocity_trends")),
            "pitchTypeSpinTrends": _coerce_dict(starter.get("pitch_type_spin_trends")),
            "leverageIndex": _enterprise_number(window.get("leverage_index"), digits=3),
            "decisionDelta": _enterprise_number(window.get("decision_delta"), digits=4),
            "estimatedWinProbabilityDelta": _enterprise_first_number(
                window.get("estimated_win_probability_delta"),
                window.get("directional_wp_opportunity"),
                digits=4,
            ),
            "starterValueNextWindow": runs_components["starterValueNextWindow"],
            "alternativeValueNextWindow": runs_components["alternativeValueNextWindow"],
            "starterRunsNextWindow": runs_components["starterRunsNextWindow"],
            "alternativeRunsNextWindow": runs_components["alternativeRunsNextWindow"],
            "transitionCost": runs_components["transitionCost"],
            "bullpenUsageCost": runs_components["bullpenUsageCost"],
            "modelImpliedRunsSaved": runs_components["modelImpliedRunsSaved"],
            "projectedRunsSaved": runs_components["projectedRunsSaved"],
            "dollarsProtected": runs_components["dollarsProtected"],
            "calibrationBucket": runs_components["calibrationBucket"],
            "calibrationSampleCount": runs_components["calibrationSampleCount"],
            "calibrationFactor": runs_components["calibrationFactor"],
            "calibrationSource": runs_components["calibrationSource"],
            "recommendation": _enterprise_recommendation(window),
            "recommendationReason": _enterprise_recommendation_reason(window),
            "stuffCurve": trajectory["stuffCurve"],
            "topReasons": [_enterprise_text(reason) for reason in top_reasons if _enterprise_text(reason)],
            "calibrationStatus": calibration_note,
            "sourceStatus": {
                "degradation": _enterprise_source_status(
                    value=starter.get("degradation_score"),
                    source="pitching_replay_model",
                    status="model",
                    notes="Pitch-level degradation composite.",
                ),
                "enhancedDegradation": _enterprise_source_status(
                    value=starter.get("enhanced_degradation_score"),
                    source="pitching_replay_model_shadow_components",
                    status="model" if starter.get("enhanced_degradation_score") is not None else "unavailable",
                    notes="Shadow enhanced model: pitch-type trends, opponent-adjusted whiff, and historical inning/TTO context. Primary signal thresholds still use degradation_score.",
                ),
                "normalizedDegradation": _enterprise_source_status(
                    value=starter.get("normalized_degradation_score"),
                    source=_enterprise_text(starter.get("normalization_source")) or "shadow_practical_cap_v1",
                    status="model" if starter.get("normalized_degradation_score") is not None else "unavailable",
                    notes="Shadow normalized 0-1 score. Inputs are capped to comparable scales; primary signal thresholds still use degradation_score.",
                ),
                "empiricalDegradation": _enterprise_source_status(
                    value=starter.get("empirical_degradation_percentile"),
                    source=_enterprise_text(starter.get("empirical_distribution_source")) or "prior_mlb_replay_windows_v1",
                    status="model" if starter.get("empirical_degradation_percentile") is not None else "unavailable",
                    notes="Shadow empirical percentile from prior chronological MLB replay windows. Null until enough prior samples exist.",
                ),
                "leverage": _enterprise_source_status(
                    value=window.get("leverage_index"),
                    source="pitching_audit_window",
                    status="available" if window.get("leverage_index") is not None else "unavailable",
                ),
                "preventableRuns": _enterprise_source_status(
                    value=runs_components.get("projectedRunsSaved"),
                    source=str(runs_components.get("calibrationSource") or "unavailable"),
                    status="model" if runs_components.get("projectedRunsSaved") is not None else "unavailable",
                    notes="Model counterfactual; not observed runs prevented.",
                ),
                "modelImpliedRuns": _enterprise_source_status(
                    value=runs_components.get("modelImpliedRunsSaved"),
                    source="starter_reliever_counterfactual_model",
                    status="model",
                ),
            },
        }

    def _enterprise_window_to_bullpen_option(
        window: dict[str, Any],
        *,
        rss_by_game_pitcher: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        candidate = _coerce_dict(window.get("top_candidate"))
        player_id = _enterprise_text(candidate.get("player_id"))
        player_name = _enterprise_text(candidate.get("player_name"))
        if not player_id and not player_name:
            return None
        available_raw = candidate.get("available")
        if isinstance(available_raw, bool):
            availability = "Available" if available_raw else "Unavailable"
            availability_source = "top_candidate.available"
        else:
            availability = "Unavailable in source"
            availability_source = "unavailable"
        role = _enterprise_text(candidate.get("bullpen_role"))
        manager_availability = _enterprise_manager_availability(candidate)
        days_rest = _enterprise_int(candidate.get("days_rest"))
        pitches_last_3 = _enterprise_int(candidate.get("pitches_last_3_days"))
        appearances_last_3 = _enterprise_int(candidate.get("appearances_last_3_days"))
        game_id = _enterprise_text(window.get("game_id"))
        rss_signal = (
            (rss_by_game_pitcher or {}).get((game_id, player_id))
            if game_id and player_id
            else None
        )
        rss_value = _enterprise_first_number(
            candidate.get("rss_score"),
            candidate.get("reliever_stress_score"),
            candidate.get("usage_fatigue"),
            _coerce_dict(rss_signal).get("rssScore"),
            digits=4,
        )
        rss_source = "explicit_candidate_rss" if _enterprise_candidate_workload_rss(candidate) is not None else (
            _enterprise_text(_coerce_dict(rss_signal).get("rssSource"), "unavailable")
            if isinstance(rss_signal, dict)
            else "unavailable"
        )
        return {
            "id": player_id or player_name,
            "name": player_name or player_id,
            "role": role.title() if role else None,
            "roleSource": "top_candidate.bullpen_role" if role else "unavailable",
            "availability": availability,
            "availabilitySource": availability_source,
            "managerAvailabilityProbability": manager_availability["probability"],
            "managerAvailabilityStatus": manager_availability["status"],
            "managerAvailabilitySource": manager_availability["source"],
            "daysRest": days_rest,
            "pitchesLast3Days": pitches_last_3,
            "appearancesLast3Days": appearances_last_3,
            "rss": round(_enterprise_clamp(float(rss_value), 0.0, 1.0), 4) if rss_value is not None else None,
            "rssLabel": _coerce_dict(rss_signal).get("rssLabel") if isinstance(rss_signal, dict) else None,
            "rssHasMeasurement": _coerce_dict(rss_signal).get("rssHasMeasurement") if isinstance(rss_signal, dict) else False,
            "rssSource": rss_source,
            "matchupFit": _enterprise_number(candidate.get("direct_matchup_fit"), digits=4),
            "usageCost": _enterprise_number(candidate.get("usage_cost"), digits=4),
            "projectedRunsAllowed": None,
            "netOptionScore": _enterprise_number(candidate.get("net_option_score"), digits=4),
            "sourceStatus": {
                "role": _enterprise_source_status(
                    value=role,
                    source="top_candidate.bullpen_role" if role else "unavailable",
                    status="usage_derived" if role else "unavailable",
                    notes="Closer/setup/middle hierarchy is not an official MLB role unless an external role feed is attached.",
                ),
                "managerAvailability": _enterprise_source_status(
                    value=manager_availability["probability"],
                    source=manager_availability["source"],
                    status="model" if manager_availability["probability"] is not None else "unavailable",
                    notes="Rule-based probability from rest and recent workload; not club day-of availability truth.",
                ),
                "rss": _enterprise_source_status(
                    value=rss_value,
                    source=rss_source,
                    status="model" if rss_value is not None else "unavailable",
                    notes=(
                        "RSS is joined from finalized postgame reliever signal when the candidate appeared in the game."
                        if rss_source == "pitching_postgame_bullpen_signal"
                        else None
                    ),
                ),
            },
        }

    def _enterprise_snapshot_opponent_runs(snapshot: dict[str, Any]) -> int | None:
        fielding_team = _enterprise_text(snapshot.get("fielding_team")).upper()
        home_team = _enterprise_text(snapshot.get("home_team")).upper()
        away_team = _enterprise_text(snapshot.get("away_team")).upper()
        home_score = _enterprise_int(snapshot.get("home_score"))
        away_score = _enterprise_int(snapshot.get("away_score"))
        if home_score is None or away_score is None:
            return None
        if fielding_team and home_team and fielding_team == home_team:
            return away_score
        if fielding_team and away_team and fielding_team == away_team:
            return home_score
        half = _enterprise_text(snapshot.get("half")).lower()
        return away_score if half == "top" else home_score if half == "bottom" else None

    def _enterprise_replay_entries(replay_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(replay_payload, dict):
            return []
        return [dict(entry) for entry in replay_payload.get("entries") or [] if isinstance(entry, dict)]

    def _enterprise_entry_pitch_count(entry: dict[str, Any] | None) -> int | None:
        snapshot = _coerce_dict((entry or {}).get("snapshot"))
        state = _coerce_dict(snapshot.get("starter_state"))
        return _enterprise_pitch_count(snapshot, state)

    def _enterprise_actual_change_details(
        window: dict[str, Any],
        matched_entry: dict[str, Any] | None,
        replay_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        entries = _enterprise_replay_entries(replay_payload)
        snapshot = _coerce_dict((matched_entry or {}).get("snapshot"))
        starter = _coerce_dict(window.get("starter"))
        pitcher_id = _enterprise_text(snapshot.get("pitcher_id") or starter.get("pitcher_id"))
        fielding_team = _enterprise_text(snapshot.get("fielding_team")).upper()
        model_pitch_id = _enterprise_text(snapshot.get("pitch_id") or window.get("pitch_id"))
        model_pitch_count = _enterprise_entry_pitch_count(matched_entry)
        model_inning = _enterprise_inning_label(window)
        replacement_id = _enterprise_text(snapshot.get("actual_replacement_pitcher_id"))
        actual_change_pitch_id = _enterprise_text(snapshot.get("actual_change_pitch_id"))
        model_index = -1
        for idx, entry in enumerate(entries):
            entry_snapshot = _coerce_dict(entry.get("snapshot"))
            if model_pitch_id and _enterprise_text(entry_snapshot.get("pitch_id")) == model_pitch_id:
                model_index = idx
                break
        if model_index < 0 and matched_entry in entries:
            model_index = entries.index(matched_entry)

        replacement_entry: dict[str, Any] | None = None
        last_same_pitcher_entry: dict[str, Any] | None = matched_entry if isinstance(matched_entry, dict) else None
        if model_index >= 0:
            for entry in entries[model_index + 1:]:
                entry_snapshot = _coerce_dict(entry.get("snapshot"))
                entry_pitcher_id = _enterprise_text(entry_snapshot.get("pitcher_id"))
                entry_fielding_team = _enterprise_text(entry_snapshot.get("fielding_team")).upper()
                if pitcher_id and entry_pitcher_id == pitcher_id:
                    last_same_pitcher_entry = entry
                    continue
                if fielding_team and entry_fielding_team and entry_fielding_team != fielding_team:
                    continue
                if replacement_id and entry_pitcher_id != replacement_id:
                    continue
                if entry_pitcher_id and (not pitcher_id or entry_pitcher_id != pitcher_id):
                    replacement_entry = entry
                    replacement_id = replacement_id or entry_pitcher_id
                    break

        if replacement_entry is None and actual_change_pitch_id:
            for entry in entries:
                entry_snapshot = _coerce_dict(entry.get("snapshot"))
                if _enterprise_text(entry_snapshot.get("pitch_id")) == actual_change_pitch_id:
                    replacement_entry = entry
                    replacement_id = replacement_id or _enterprise_text(entry_snapshot.get("pitcher_id"))
                    break

        replacement_snapshot = _coerce_dict((replacement_entry or {}).get("snapshot"))
        last_same_snapshot = _coerce_dict((last_same_pitcher_entry or {}).get("snapshot"))
        replacement_name = _enterprise_text(replacement_snapshot.get("pitcher_name"))
        if not replacement_name and replacement_id:
            candidate_sources = [snapshot, last_same_snapshot, replacement_snapshot]
            candidate_sources.extend(
                _coerce_dict(entry.get("snapshot"))
                for entry in entries
                if isinstance(entry, dict)
            )
            for candidate_source in candidate_sources:
                candidates = candidate_source.get("reliever_candidates")
                if not isinstance(candidates, list):
                    continue
                for candidate in candidates:
                    candidate_dict = _coerce_dict(candidate)
                    if _enterprise_text(candidate_dict.get("player_id")) == replacement_id:
                        replacement_name = _enterprise_text(candidate_dict.get("player_name"))
                        if replacement_name:
                            break
                if replacement_name:
                    break
        model_runs = _enterprise_snapshot_opponent_runs(snapshot)
        exit_runs = _enterprise_snapshot_opponent_runs(last_same_snapshot)
        runs_after = (
            max(0, int(exit_runs) - int(model_runs))
            if isinstance(model_runs, int) and isinstance(exit_runs, int)
            else None
        )
        actual_change_after_pitches = _enterprise_first_number(
            snapshot.get("official_actual_change_after_pitches"),
            snapshot.get("actual_change_after_pitches"),
            digits=0,
        )
        actual_change_after_batters = _enterprise_first_number(
            snapshot.get("official_actual_change_after_batters"),
            snapshot.get("actual_change_after_batters"),
            digits=0,
        )
        actual_change_pitch_count = _enterprise_first_number(
            snapshot.get("official_pull_pitch_count_in_game"),
            _enterprise_entry_pitch_count(last_same_pitcher_entry),
            digits=0,
        )
        replacement_pitch_count = _enterprise_entry_pitch_count(replacement_entry)
        actual_change_inning = None
        inning_snapshot = replacement_snapshot or last_same_snapshot
        if inning_snapshot:
            inning = _enterprise_int(inning_snapshot.get("inning"))
            half = _enterprise_text(inning_snapshot.get("half")).lower()
            if inning is not None:
                actual_change_inning = f"{'Top' if half == 'top' else 'Bottom' if half == 'bottom' else 'Inning'} {inning}"
        return {
            "modelWindowPitchId": model_pitch_id or None,
            "modelWindowPitchCount": model_pitch_count,
            "modelWindowInning": model_inning,
            "actualReplacementPitcherId": replacement_id or None,
            "actualReplacementPitcher": replacement_name or None,
            "actualChangePitchId": actual_change_pitch_id or _enterprise_text(replacement_snapshot.get("pitch_id")) or None,
            "actualChangeInning": actual_change_inning,
            "actualChangePitchCount": int(actual_change_pitch_count) if actual_change_pitch_count is not None else None,
            "actualReplacementFirstPitchCount": replacement_pitch_count,
            "actualChangeAfterPitches": int(actual_change_after_pitches) if actual_change_after_pitches is not None else None,
            "actualChangeAfterBatters": int(actual_change_after_batters) if actual_change_after_batters is not None else None,
            "actualChangeWithinNextPocket": bool(snapshot.get("actual_change_within_next_pocket")) if "actual_change_within_next_pocket" in snapshot else None,
            "runsAfterModelWindow": runs_after,
            "runsAfterModelWindowSource": "pitching_replay_score_progression" if runs_after is not None else "unavailable",
        }

    def _enterprise_first_present(*values: Any) -> Any:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return None

    def _enterprise_replay_final_scores(replay_payload: dict[str, Any] | None) -> tuple[int | None, int | None]:
        if not isinstance(replay_payload, dict):
            return None, None
        game = _coerce_dict(replay_payload.get("game"))
        home_score = _enterprise_int(
            _enterprise_first_present(
                game.get("final_home_score"),
                game.get("finalHomeScore"),
                game.get("home_final_score"),
                game.get("homeScore"),
            )
        )
        away_score = _enterprise_int(
            _enterprise_first_present(
                game.get("final_away_score"),
                game.get("finalAwayScore"),
                game.get("away_final_score"),
                game.get("awayScore"),
            )
        )
        if home_score is not None and away_score is not None:
            return home_score, away_score
        for entry in reversed(_enterprise_replay_entries(replay_payload)):
            snapshot = _coerce_dict(entry.get("snapshot"))
            entry_home = _enterprise_int(snapshot.get("home_score"))
            entry_away = _enterprise_int(snapshot.get("away_score"))
            if entry_home is not None and entry_away is not None:
                return entry_home, entry_away
        return home_score, away_score

    def _preventable_runs_opportunity_window(row: dict[str, Any]) -> dict[str, Any]:
        pitcher_id = _enterprise_text(
            _enterprise_first_present(row.get("pitcherId"), row.get("pitcher_id"), row.get("mlbPitcherId"), row.get("mlb_pitcher_id"))
        )
        pitcher_name = _enterprise_text(_enterprise_first_present(row.get("pitcherName"), row.get("pitcher_name")))
        pitch_count = _enterprise_first_present(
            row.get("pitchCount"),
            row.get("pitch_count"),
            row.get("pitch_count_in_game"),
            row.get("pitchNumber"),
            row.get("pitch_number"),
        )
        return {
            "pitch_id": _enterprise_text(_enterprise_first_present(row.get("pitchId"), row.get("pitch_id"))),
            "inning": _enterprise_first_present(row.get("inning"), row.get("inning_number")),
            "half": _enterprise_first_present(row.get("half"), row.get("inningHalf"), row.get("inning_half"), row.get("topBottom"), row.get("top_bottom")),
            "starter": {
                "pitcher_id": pitcher_id,
                "pitcher_name": pitcher_name,
                "pitch_count_in_game": pitch_count,
            },
        }

    def _preventable_runs_enrich_display_fields(
        row: dict[str, Any],
        replay_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        enriched = dict(row)
        window = _preventable_runs_opportunity_window(enriched)
        matched_entry = _enterprise_replay_entry_for_window(window, replay_payload) if isinstance(replay_payload, dict) else None
        matched_snapshot = _coerce_dict((matched_entry or {}).get("snapshot"))
        final_home_score, final_away_score = _enterprise_replay_final_scores(replay_payload)
        actual_change = (
            _enterprise_actual_change_details(window, matched_entry, replay_payload)
            if isinstance(replay_payload, dict)
            else {}
        )

        enriched["currentHomeScore"] = _enterprise_int(
            _enterprise_first_present(enriched.get("currentHomeScore"), enriched.get("current_home_score"), matched_snapshot.get("home_score"))
        )
        enriched["currentAwayScore"] = _enterprise_int(
            _enterprise_first_present(enriched.get("currentAwayScore"), enriched.get("current_away_score"), matched_snapshot.get("away_score"))
        )
        enriched["finalHomeScore"] = _enterprise_int(
            _enterprise_first_present(enriched.get("finalHomeScore"), enriched.get("final_home_score"), final_home_score)
        )
        enriched["finalAwayScore"] = _enterprise_int(
            _enterprise_first_present(enriched.get("finalAwayScore"), enriched.get("final_away_score"), final_away_score)
        )
        enriched["actualChangeInning"] = _enterprise_text(
            _enterprise_first_present(enriched.get("actualChangeInning"), enriched.get("actual_change_inning"), actual_change.get("actualChangeInning"))
        ) or None
        enriched["actualChangePitchCount"] = _enterprise_int(
            _enterprise_first_present(
                enriched.get("actualChangePitchCount"),
                enriched.get("actual_change_pitch_count"),
                actual_change.get("actualChangePitchCount"),
            )
        )
        enriched["actualReplacementPitcher"] = _enterprise_text(
            _enterprise_first_present(
                enriched.get("actualReplacementPitcher"),
                enriched.get("actual_replacement_pitcher"),
                actual_change.get("actualReplacementPitcher"),
            )
        ) or None
        enriched["actualReplacementPitcherId"] = _enterprise_text(
            _enterprise_first_present(
                enriched.get("actualReplacementPitcherId"),
                enriched.get("actual_replacement_pitcher_id"),
                actual_change.get("actualReplacementPitcherId"),
            )
        ) or None
        enriched["runsAfterModelWindow"] = _enterprise_int(
            _enterprise_first_present(
                enriched.get("runsAfterModelWindow"),
                enriched.get("runs_after_model_window"),
                actual_change.get("runsAfterModelWindow"),
            )
        )
        if actual_change.get("actualReplacementFirstPitchCount") is not None:
            enriched["actualReplacementFirstPitchCount"] = actual_change.get("actualReplacementFirstPitchCount")
        if actual_change.get("actualChangeAfterPitches") is not None:
            enriched["actualChangeAfterPitches"] = actual_change.get("actualChangeAfterPitches")
        if actual_change.get("actualChangeAfterBatters") is not None:
            enriched["actualChangeAfterBatters"] = actual_change.get("actualChangeAfterBatters")
        if actual_change.get("runsAfterModelWindowSource"):
            enriched["runsAfterModelWindowSource"] = actual_change.get("runsAfterModelWindowSource")
        return enriched

    def _enterprise_window_to_audit_row(
        window: dict[str, Any],
        *,
        note: str,
        timing: str,
        replay_payload: dict[str, Any] | None = None,
        calibration: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        starter = _coerce_dict(window.get("starter"))
        flags = _coerce_dict(window.get("flags"))
        top_candidate = _coerce_dict(window.get("top_candidate"))
        status = _enterprise_text(window.get("status"), "Decision")
        pitcher = _enterprise_text(starter.get("pitcher_name"), "Pitcher pending")
        candidate_name = _enterprise_text(top_candidate.get("player_name"))
        matched_entry = _enterprise_replay_entry_for_window(window, replay_payload)
        actual_change = _enterprise_actual_change_details(window, matched_entry, replay_payload)
        raw_runs_components = _enterprise_projected_runs_components(window, matched_entry)
        runs_components = _enterprise_apply_runs_saved_calibration(window, raw_runs_components, calibration)
        projected_runs = _enterprise_number(runs_components.get("projectedRunsSaved"), digits=3)
        actual_decision = "Changed after the model window" if flags.get("delayed_change_window") else "Stayed through the model window"
        if flags.get("justified_stay_window") or flags.get("bullpen_thin_stay"):
            actual_decision = "Hold was contextually justified"
        if actual_change.get("actualReplacementPitcher"):
            lead = actual_change.get("actualChangeAfterPitches")
            lead_text = f" after {lead} pitches" if lead is not None else ""
            actual_decision = f"Changed to {actual_change['actualReplacementPitcher']}{lead_text}"
        recommended_decision = _enterprise_recommendation(window)
        candidate_text = f" to {candidate_name}" if candidate_name else ""
        model_runs = _enterprise_number(runs_components.get("modelImpliedRunsSaved"), digits=3)
        if projected_runs is not None and projected_runs > 0:
            counterfactual = (
                f"Changing{candidate_text} at the model window has a calibrated model estimate of "
                f"{projected_runs:.2f} preventable runs."
            )
        elif projected_runs is not None and projected_runs < 0:
            counterfactual = (
                "The counterfactual change did not clear the run-saving threshold after bullpen availability "
                "and usage cost were included."
            )
        elif model_runs is not None:
            counterfactual = (
                f"Calibrated preventable-run estimate unavailable; raw model-implied opportunity is "
                f"{model_runs:.2f} runs."
            )
        else:
            counterfactual = "Counterfactual run impact unavailable in the audit artifact."
        return {
            "id": _enterprise_text(window.get("window_id"), f"{_enterprise_text(window.get('game_id'))}:{pitcher}:{status}"),
            "game": f"{_enterprise_text(window.get('date'))} {_enterprise_text(window.get('matchup'), 'Game pending')}".strip(),
            "decision": f"{pitcher} {status.replace('_', ' ')}",
            "timing": timing,
            "pitcher": pitcher,
            "team": _enterprise_text(window.get("decision_team")),
            "opponent": _enterprise_text(window.get("opponent_team")),
            "inning": _enterprise_inning_label(window),
            "leverageIndex": _enterprise_number(window.get("leverage_index"), digits=3),
            "actualDecision": actual_decision,
            "recommendedDecision": recommended_decision,
            "bestAlternative": candidate_name or None,
            "modelWindowPitchId": actual_change.get("modelWindowPitchId"),
            "modelWindowPitchCount": actual_change.get("modelWindowPitchCount"),
            "modelWindowInning": actual_change.get("modelWindowInning"),
            "actualReplacementPitcherId": actual_change.get("actualReplacementPitcherId"),
            "actualReplacementPitcher": actual_change.get("actualReplacementPitcher"),
            "actualChangePitchId": actual_change.get("actualChangePitchId"),
            "actualChangeInning": actual_change.get("actualChangeInning"),
            "actualChangePitchCount": actual_change.get("actualChangePitchCount"),
            "actualReplacementFirstPitchCount": actual_change.get("actualReplacementFirstPitchCount"),
            "actualChangeAfterPitches": actual_change.get("actualChangeAfterPitches"),
            "actualChangeAfterBatters": actual_change.get("actualChangeAfterBatters"),
            "actualChangeWithinNextPocket": actual_change.get("actualChangeWithinNextPocket"),
            "opportunityDescription": _enterprise_recommendation_reason(window),
            "counterfactualSummary": counterfactual,
            "starterValueNextWindow": runs_components["starterValueNextWindow"],
            "alternativeValueNextWindow": runs_components["alternativeValueNextWindow"],
            "starterRunsNextWindow": runs_components["starterRunsNextWindow"],
            "alternativeRunsNextWindow": runs_components["alternativeRunsNextWindow"],
            "modelImpliedRunsSaved": runs_components["modelImpliedRunsSaved"],
            "projectedRunsSaved": runs_components["projectedRunsSaved"],
            "currentDegradation": _enterprise_number(starter.get("degradation_score"), digits=3),
            "enhancedDegradation": _enterprise_number(starter.get("enhanced_degradation_score"), digits=3),
            "normalizedDegradation": _enterprise_number(starter.get("normalized_degradation_score"), digits=4),
            "normalizedComponentScores": _coerce_dict(starter.get("normalized_component_scores")),
            "normalizedComponentWeights": _coerce_dict(starter.get("normalized_component_weights")),
            "normalizedWeightedComponents": _coerce_dict(starter.get("normalized_weighted_components")),
            "normalizationSource": _enterprise_text(starter.get("normalization_source")) or None,
            "empiricalDegradationPercentile": _enterprise_number(starter.get("empirical_degradation_percentile"), digits=4),
            "empiricalDegradationSampleCount": int(starter.get("empirical_degradation_sample_count") or 0),
            "pitcherEmpiricalDegradationPercentile": _enterprise_number(starter.get("pitcher_empirical_degradation_percentile"), digits=4),
            "pitcherEmpiricalDegradationSampleCount": int(starter.get("pitcher_empirical_degradation_sample_count") or 0),
            "empiricalComponentPercentiles": _coerce_dict(starter.get("empirical_component_percentiles")),
            "empiricalPitchTypePercentiles": _coerce_dict(starter.get("empirical_pitch_type_percentiles")),
            "empiricalDistributionSource": _enterprise_text(starter.get("empirical_distribution_source")) or None,
            "componentContributions": _coerce_dict(starter.get("component_contributions")),
            "pitchTypeVelocityTrends": _coerce_dict(starter.get("pitch_type_velocity_trends")),
            "pitchTypeSpinTrends": _coerce_dict(starter.get("pitch_type_spin_trends")),
            "opponentAdjustedWhiffDrop": _enterprise_number(starter.get("opponent_adjusted_whiff_drop"), digits=4),
            "inningDecayFactor": _enterprise_number(starter.get("inning_decay_factor"), digits=4),
            "ttoDecayFactor": _enterprise_number(starter.get("tto_decay_factor"), digits=4),
            "calibrationSampleCount": runs_components["calibrationSampleCount"],
            "calibrationFactor": runs_components["calibrationFactor"],
            "estimatedWinProbabilityDelta": _enterprise_first_number(
                window.get("directional_wp_opportunity"),
                window.get("estimated_win_probability_delta"),
                digits=4,
            ),
            "realizedDelayTax": _enterprise_number(window.get("realized_delay_tax"), digits=4),
            "actualRunsAfter": actual_change.get("runsAfterModelWindow"),
            "runsAfterModelWindow": actual_change.get("runsAfterModelWindow"),
            "runsAfterModelWindowSource": actual_change.get("runsAfterModelWindowSource"),
            "note": note,
            "sourceStatus": {
                "actualDecision": _enterprise_source_status(
                    value=actual_decision,
                    source="pitching_replay_actual_change_fields" if actual_change.get("actualReplacementPitcherId") else "pitching_audit_flags",
                    status="available" if actual_change.get("actualReplacementPitcherId") else "model_context",
                    notes="Observed replacement timing from replay when available; otherwise derived from audit timing flags.",
                ),
                "actualReplacement": _enterprise_source_status(
                    value=actual_change.get("actualReplacementPitcher") or actual_change.get("actualReplacementPitcherId"),
                    source="pitching_replay_actual_change_fields",
                    status="available" if actual_change.get("actualReplacementPitcherId") else "unavailable",
                ),
                "runsAfterModelWindow": _enterprise_source_status(
                    value=actual_change.get("runsAfterModelWindow"),
                    source=str(actual_change.get("runsAfterModelWindowSource") or "unavailable"),
                    status="available" if actual_change.get("runsAfterModelWindow") is not None else "unavailable",
                ),
                "bestAlternative": _enterprise_source_status(
                    value=candidate_name or None,
                    source="top_candidate",
                    status="model" if candidate_name else "unavailable",
                ),
                "normalizedDegradation": _enterprise_source_status(
                    value=starter.get("normalized_degradation_score"),
                    source=_enterprise_text(starter.get("normalization_source")) or "shadow_practical_cap_v1",
                    status="model" if starter.get("normalized_degradation_score") is not None else "unavailable",
                    notes="Shadow normalized 0-1 score; not used as a production threshold.",
                ),
                "empiricalDegradation": _enterprise_source_status(
                    value=starter.get("empirical_degradation_percentile"),
                    source=_enterprise_text(starter.get("empirical_distribution_source")) or "prior_mlb_replay_windows_v1",
                    status="model" if starter.get("empirical_degradation_percentile") is not None else "unavailable",
                    notes="Shadow empirical percentile from prior chronological MLB replay windows. Null until enough prior samples exist.",
                ),
                "preventableRuns": _enterprise_source_status(
                    value=runs_components["projectedRunsSaved"],
                    source=str(runs_components.get("calibrationSource") or "unavailable"),
                    status="model" if runs_components["projectedRunsSaved"] is not None else "unavailable",
                ),
            },
        }

    def _enterprise_rank_decision_window(window: dict[str, Any]) -> tuple[str, int, float, float, str]:
        status_rank = {"PULL_NOW": 4, "PREP": 3, "WATCH": 2, "STAY": 1}
        starter = _coerce_dict(window.get("starter"))
        return (
            _enterprise_text(window.get("date")),
            status_rank.get(_enterprise_text(window.get("status")).upper(), 0),
            abs(_enterprise_number(window.get("decision_delta"), digits=6) or 0.0),
            _enterprise_number(starter.get("degradation_score"), digits=6) or 0.0,
            _enterprise_text(window.get("window_id")),
        )

    def _enterprise_pitching_replay_for_features(
        game_id: str,
        *,
        league: str,
    ) -> dict[str, Any] | None:
        # Use the stored normalized replay directly. The public replay endpoint augments
        # with official pitch facts, which can trigger external StatsAPI calls and is not
        # needed for enterprise run-saving feature calculations.
        normalized_game_id = _enterprise_text(game_id)
        if not normalized_game_id:
            return None
        league_cache = STATE.pitching_replay_cache.setdefault(league, {})
        cached = league_cache.get(normalized_game_id)
        if isinstance(cached, dict) and cached:
            return dict(cached)
        try:
            payload = _pitching_store_get(_pitching_store_key("replay", normalized_game_id, league=league))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            normalized = _normalize_pitching_replay_payload(dict(payload))
            league_cache[normalized_game_id] = dict(normalized)
            return dict(normalized)
        return None

    _TRIPLE_A_PARENT_CLUBS = {
        "ABQ": ("Albuquerque", "Colorado Rockies"),
        "BUF": ("Buffalo", "Toronto Blue Jays"),
        "CLT": ("Charlotte", "Chicago White Sox"),
        "COL": ("Columbus", "Cleveland Guardians"),
        "DUR": ("Durham", "Tampa Bay Rays"),
        "ELP": ("El Paso", "San Diego Padres"),
        "GWN": ("Gwinnett", "Atlanta Braves"),
        "IND": ("Indianapolis", "Pittsburgh Pirates"),
        "IOW": ("Iowa", "Chicago Cubs"),
        "JAX": ("Jacksonville", "Miami Marlins"),
        "LAS": ("Las Vegas", "Athletics"),
        "LHV": ("Lehigh Valley", "Philadelphia Phillies"),
        "LOU": ("Louisville", "Cincinnati Reds"),
        "MEM": ("Memphis", "St. Louis Cardinals"),
        "NAS": ("Nashville", "Milwaukee Brewers"),
        "NOR": ("Norfolk", "Baltimore Orioles"),
        "OKC": ("Oklahoma City", "Los Angeles Dodgers"),
        "OMA": ("Omaha", "Kansas City Royals"),
        "RNO": ("Reno", "Arizona Diamondbacks"),
        "ROC": ("Rochester", "Washington Nationals"),
        "SAC": ("Sacramento", "San Francisco Giants"),
        "SLC": ("Salt Lake", "Los Angeles Angels"),
        "STP": ("St. Paul", "Minnesota Twins"),
        "SWB": ("Scranton/WB", "New York Yankees"),
        "SYR": ("Syracuse", "New York Mets"),
        "TAC": ("Tacoma", "Seattle Mariners"),
        "TOL": ("Toledo", "Detroit Tigers"),
        "WOR": ("Worcester", "Boston Red Sox"),
    }

    def _enterprise_triple_a_affiliate(team: str) -> tuple[str, str]:
        normalized = _enterprise_text(team).upper()
        label, parent = _TRIPLE_A_PARENT_CLUBS.get(normalized, (normalized or "Triple-A", "Parent club pending"))
        return f"{label} ({normalized})" if normalized else label, parent

    def _enterprise_candidate_role(max_pitch_count: int, first_inning: int | None) -> str:
        if max_pitch_count >= 45 or (first_inning is not None and first_inning <= 2 and max_pitch_count >= 35):
            return "Starter"
        return "Reliever"

    def _enterprise_recommended_conversion_role(
        *,
        relief_score: float,
        short_window_stuff_plus: float,
        second_window_decay: float,
        max_pitch_count: int,
        mirage_risk: float,
    ) -> str:
        if mirage_risk >= 0.78:
            return "Mirage risk"
        if relief_score >= 78 and second_window_decay <= 9:
            return "2-inning weapon"
        if max_pitch_count >= 50 and relief_score >= 66 and second_window_decay <= 16:
            return "Bulk bridge"
        if short_window_stuff_plus >= 108 and second_window_decay > 16:
            return "Pocket specialist"
        return "Watchlist"

    def _enterprise_triple_a_conversion_candidates(limit: int) -> list[dict[str, Any]]:
        games = _get_pitching_games(league=TRIPLE_A_PITCHING_LEAGUE)
        if not games:
            return []
        candidates: dict[str, dict[str, Any]] = {}
        for game in games[:80]:
            game_id = _enterprise_text(game.get("game_id"))
            if not game_id:
                continue
            replay = _enterprise_pitching_replay_for_features(game_id, league=TRIPLE_A_PITCHING_LEAGUE)
            if not isinstance(replay, dict):
                continue
            for entry in replay.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                snapshot = _coerce_dict(entry.get("snapshot"))
                state = _coerce_dict(snapshot.get("starter_state"))
                pitcher_id = _enterprise_text(snapshot.get("pitcher_id"))
                pitcher_name = _enterprise_text(snapshot.get("pitcher_name"))
                team = _enterprise_text(snapshot.get("fielding_team")).upper()
                if not pitcher_id or not pitcher_name or not team:
                    continue
                pitch_count = _enterprise_pitch_count(snapshot, state)
                degradation = _enterprise_number(state.get("degradation_score"), digits=6)
                stuff_score = _enterprise_stuff_score_from_degradation(degradation)
                if pitch_count is None or degradation is None or stuff_score is None:
                    continue
                key = f"{team}:{pitcher_id}"
                row = candidates.setdefault(
                    key,
                    {
                        "pitcher_id": pitcher_id,
                        "pitcher_name": pitcher_name,
                        "team": team,
                        "pitch_counts": [],
                        "scores": [],
                        "degradations": [],
                        "innings": [],
                        "velos": [],
                    },
                )
                row["pitch_counts"].append(int(pitch_count))
                row["scores"].append(float(stuff_score))
                row["degradations"].append(float(degradation))
                inning = _enterprise_int(snapshot.get("inning"))
                if inning is not None:
                    row["innings"].append(int(inning))
                velo = _enterprise_number(snapshot.get("release_speed"), digits=3)
                if velo is not None:
                    row["velos"].append(float(velo))

        result: list[dict[str, Any]] = []
        for row in candidates.values():
            pitch_counts = [int(value) for value in row.get("pitch_counts") or []]
            scores = [float(value) for value in row.get("scores") or []]
            degradations = [float(value) for value in row.get("degradations") or []]
            if len(scores) < 12 or not pitch_counts:
                continue
            max_pitch_count = max(pitch_counts)
            innings = [int(value) for value in row.get("innings") or [] if isinstance(value, int)]
            first_inning = min(innings) if innings else None
            first_window = [
                score
                for count, score in zip(pitch_counts, scores)
                if int(count) <= min(35, max_pitch_count)
            ]
            second_window = [
                score
                for count, score in zip(pitch_counts, scores)
                if 36 <= int(count) <= 65
            ]
            if not first_window:
                continue
            first_score = _enterprise_mean(first_window) or 0.0
            second_score = _enterprise_mean(second_window) if second_window else None
            second_window_decay = max(0.0, first_score - (second_score if second_score is not None else scores[-1]))
            short_window_stuff_plus = _enterprise_clamp(100.0 + ((first_score - 70.0) * 1.45), 40.0, 140.0)
            avg_degradation = _enterprise_mean(degradations) or 0.0
            max_degradation = max(degradations)
            velo_values = [float(value) for value in row.get("velos") or []]
            avg_velo = _enterprise_mean(velo_values) if velo_values else None
            velo_bonus = _enterprise_clamp(((avg_velo or 93.0) - 93.0) * 1.5, -6.0, 8.0)
            starter_conversion_bonus = 5.0 if max_pitch_count >= 45 else 0.0
            relief_score = _enterprise_clamp(
                ((short_window_stuff_plus - 70.0) * 0.75)
                - (second_window_decay * 1.6)
                - (avg_degradation * 6.0)
                + velo_bonus
                + starter_conversion_bonus
                + 48.0,
                0.0,
                100.0,
            )
            tracked_pitches = len(scores)
            volatility = _enterprise_mean([abs(scores[i] - scores[i - 1]) for i in range(1, len(scores))]) or 0.0
            mirage_risk = _enterprise_clamp(
                0.82
                - min(0.42, tracked_pitches / 150.0)
                + min(0.22, volatility / 70.0)
                + min(0.18, max_degradation / 12.0),
                0.05,
                0.95,
            )
            confidence = _enterprise_clamp(0.18 + min(0.58, tracked_pitches / 120.0) - (mirage_risk * 0.18), 0.15, 0.86)
            projected_runs_saved = round(max(0.0, (relief_score - 55.0) / 90.0), 3)
            affiliate, parent_club = _enterprise_triple_a_affiliate(str(row.get("team") or ""))
            recommended_role = _enterprise_recommended_conversion_role(
                relief_score=relief_score,
                short_window_stuff_plus=short_window_stuff_plus,
                second_window_decay=second_window_decay,
                max_pitch_count=max_pitch_count,
                mirage_risk=mirage_risk,
            )
            if recommended_role == "Mirage risk" and relief_score < 62:
                continue
            result.append(
                {
                    "id": f"{row.get('team')}:{row.get('pitcher_id')}",
                    "affiliate": affiliate,
                    "parentClub": parent_club,
                    "pitcher": _enterprise_text(row.get("pitcher_name"), "Pitcher pending"),
                    "currentRole": _enterprise_candidate_role(max_pitch_count, first_inning),
                    "recommendedRole": recommended_role,
                    "shortWindowStuffPlus": int(round(short_window_stuff_plus)),
                    "secondWindowDecay": round(second_window_decay, 1),
                    "reliefConversionScore": int(round(relief_score)),
                    "projectedRunsSaved": projected_runs_saved,
                    "confidence": round(confidence, 3),
                    "mirageRisk": round(mirage_risk, 3),
                    "trackedPitches": int(tracked_pitches),
                    "note": (
                        f"Short-window stuff {first_score:.0f}/100; "
                        f"second-window decay {second_window_decay:.1f}; "
                        f"max degradation {max_degradation:.2f}."
                    ),
                }
            )
        result.sort(
            key=lambda item: (
                -float(item.get("projectedRunsSaved") or 0.0),
                -int(item.get("reliefConversionScore") or 0),
                float(item.get("mirageRisk") or 1.0),
                str(item.get("pitcher") or ""),
            )
        )
        return result[:limit]

    def _enterprise_run_saving_board_payload(
        *,
        league: str,
        limit: int,
        team: str | None = None,
        date_filter: str | None = None,
        year: str | None = None,
    ) -> dict[str, Any]:
        summary = _pitching_summary_payload(league=league)
        audit = _pitching_audit_payload(league=league)
        all_windows = [
            dict(window)
            for window in audit.get("decision_windows_all") or []
            if isinstance(window, dict)
        ]
        team_filter = _enterprise_text(team).upper()
        date_text = _enterprise_text(date_filter)
        year_text = _enterprise_text(year)
        if team_filter:
            all_windows = [
                window
                for window in all_windows
                if _enterprise_text(window.get("decision_team")).upper() == team_filter
                or _enterprise_text(window.get("opponent_team")).upper() == team_filter
                or team_filter in _enterprise_text(window.get("matchup")).upper().replace(" ", "")
            ]
        if date_text:
            all_windows = [window for window in all_windows if _enterprise_text(window.get("date")) == date_text]
        if year_text:
            all_windows = [window for window in all_windows if _enterprise_text(window.get("date")).startswith(year_text)]

        def _enterprise_window_matches_board_filters(window: dict[str, Any]) -> bool:
            if team_filter and not (
                _enterprise_text(window.get("decision_team")).upper() == team_filter
                or _enterprise_text(window.get("opponent_team")).upper() == team_filter
                or team_filter in _enterprise_text(window.get("matchup")).upper().replace(" ", "")
            ):
                return False
            if date_text and _enterprise_text(window.get("date")) != date_text:
                return False
            if year_text and not _enterprise_text(window.get("date")).startswith(year_text):
                return False
            return True

        calibration = _enterprise_build_runs_saved_calibration(all_windows)
        ranked_windows = sorted(all_windows, key=_enterprise_rank_decision_window, reverse=True)[:limit]
        replay_by_game: dict[str, dict[str, Any] | None] = {}
        for window in ranked_windows:
            game_id = _enterprise_text(window.get("game_id"))
            if game_id and game_id not in replay_by_game:
                replay_by_game[game_id] = _enterprise_pitching_replay_for_features(game_id, league=league)
        postgame_report_cache: dict[str, dict[str, Any]] = {}
        rss_by_game_pitcher: dict[tuple[str, str], dict[str, Any]] = {}
        for window in ranked_windows:
            game_id = _enterprise_text(window.get("game_id"))
            player_id = _enterprise_text(_coerce_dict(window.get("top_candidate")).get("player_id"))
            if not game_id or not player_id:
                continue
            rss_signal = _enterprise_rss_signal_for_pitcher(
                game_id,
                player_id,
                league=league,
                cache=postgame_report_cache,
            )
            if isinstance(rss_signal, dict):
                rss_by_game_pitcher[(game_id, player_id)] = rss_signal
        decisions = [
            _enterprise_window_to_decision(
                window,
                replay_payload=replay_by_game.get(_enterprise_text(window.get("game_id"))),
                calibration=calibration,
            )
            for window in ranked_windows
        ]

        bullpen_options: list[dict[str, Any]] = []
        seen_options: set[str] = set()
        for window in ranked_windows:
            option = _enterprise_window_to_bullpen_option(window, rss_by_game_pitcher=rss_by_game_pitcher)
            if option is None:
                continue
            option_id = _enterprise_text(option.get("id"))
            if option_id in seen_options:
                continue
            seen_options.add(option_id)
            bullpen_options.append(option)

        audit_rows: list[dict[str, Any]] = []
        audit_sources = [
            ("delayed_change_windows", "Late", "Manager changed pitchers after the model's earlier action window."),
            ("missed_hook_windows", "Held", "Model identified a hook opportunity, but the starter stayed through the next window."),
            ("justified_stay_windows", "Held", "Hold window where available alternatives did not clearly improve the decision."),
            ("bullpen_thin_stays", "Held", "Hold window flagged as bullpen-thin; alternative availability drove the decision."),
        ]
        seen_audits: set[str] = set()
        for key, timing, note in audit_sources:
            for window in audit.get(key) or []:
                if not isinstance(window, dict):
                    continue
                if not _enterprise_window_matches_board_filters(window):
                    continue
                game_id = _enterprise_text(window.get("game_id"))
                if game_id and game_id not in replay_by_game:
                    replay_by_game[game_id] = _enterprise_pitching_replay_for_features(game_id, league=league)
                audit_replay_payload = _get_pitching_replay(game_id, league=league) if game_id else replay_by_game.get(game_id)
                row = _enterprise_window_to_audit_row(
                    window,
                    note=note,
                    timing=timing,
                    replay_payload=audit_replay_payload,
                    calibration=calibration,
                )
                row_id = _enterprise_text(row.get("id"))
                if row_id in seen_audits:
                    continue
                seen_audits.add(row_id)
                audit_rows.append(row)
                if len(audit_rows) >= limit:
                    break
            if len(audit_rows) >= limit:
                break

        source_summary = _coerce_dict(audit.get("source_summary"))
        triple_a_candidates = (
            _enterprise_triple_a_conversion_candidates(limit)
            if league == TRIPLE_A_PITCHING_LEAGUE
            else []
        )
        data_coverage = {
            "decisionWindows": len(decisions),
            "calibratedPreventableRunWindows": sum(1 for item in decisions if item.get("projectedRunsSaved") is not None),
            "modelImpliedRunWindows": sum(1 for item in decisions if item.get("modelImpliedRunsSaved") is not None),
            "bullpenOptions": len(bullpen_options),
            "bullpenOptionsWithRole": sum(1 for item in bullpen_options if item.get("role")),
            "bullpenOptionsWithManagerAvailability": sum(
                1 for item in bullpen_options if item.get("managerAvailabilityProbability") is not None
            ),
            "bullpenOptionsWithRss": sum(
                1 for item in bullpen_options if item.get("rss") is not None
            ),
            "bullpenOptionsWithExplicitRss": sum(
                1 for item in bullpen_options if item.get("rssSource") == "explicit_candidate_rss"
            ),
            "auditRows": len(audit_rows),
            "tripleAConversionCandidates": len(triple_a_candidates),
        }
        return {
            "summary": {
                "generatedAt": summary.get("generated_at") or source_summary.get("generated_at"),
                "league": league,
                "dataMode": "enterprise_run_saving_v1",
                "calibrationStatus": "Preventable Runs is a model counterfactual. Calibration uses comparable artifact buckets and proxy outcome windows; unavailable buckets return null instead of falling back to raw model.",
                "calibrationWindowCount": _enterprise_int(calibration.get("sourceWindowCount")),
                "calibrationBucketCount": _enterprise_int(calibration.get("bucketCount")),
                "decisionCount": len(decisions),
                "bullpenOptionCount": len(bullpen_options),
                "auditCount": len(audit_rows),
                "tripleAConversionCandidateCount": len(triple_a_candidates),
                "sourceSnapshotCount": _enterprise_int(summary.get("snapshot_count") or source_summary.get("snapshot_count")),
                "sourceGameCount": _enterprise_int(summary.get("game_count") or source_summary.get("game_count")),
                "dataCoverage": data_coverage,
            },
            "decisions": decisions,
            "bullpenOptions": bullpen_options,
            "audits": audit_rows,
            "tripleAConversionCandidates": triple_a_candidates,
            "calibration": {
                "sourceWindowCount": calibration.get("sourceWindowCount"),
                "bucketCount": calibration.get("bucketCount"),
                "minExactBucketSamples": calibration.get("minExactBucketSamples"),
            },
        }

    def _enterprise_team_match(team: str | None, *values: Any) -> bool:
        normalized = _normalize_pitching_recap_team(team)
        if not normalized:
            normalized = _enterprise_text(team).upper()
        if not normalized:
            return True
        candidates = {_enterprise_text(value).upper() for value in values if _enterprise_text(value)}
        compact_candidates = {value.replace(" ", "") for value in candidates}
        return normalized in candidates or normalized in compact_candidates

    def _enterprise_pitching_games_payload(
        *,
        league: str,
        team: str | None = None,
        date_filter: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        summary = _pitching_summary_payload(league=league)
        games = _get_pitching_games(league=league)
        if not games:
            summary_game_count = summary.get("game_count")
            if summary_game_count is not None and int(summary_game_count or 0) <= 0:
                games = []
            else:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Pitching games catalog unavailable even though a summary exists. "
                        "Run /v1/pitching/refresh again."
                    ),
                )
        date_text = _enterprise_text(date_filter)
        catalog: list[dict[str, Any]] = []
        for item in games or []:
            if not isinstance(item, dict):
                continue
            home = _enterprise_text(item.get("home_team"))
            away = _enterprise_text(item.get("away_team"))
            if team and not _enterprise_team_match(team, home, away):
                continue
            if date_text and _enterprise_text(item.get("date")) != date_text:
                continue
            row = dict(item)
            row["matchup"] = f"{away} @ {home}".strip(" @")
            row["generated_at"] = summary.get("generated_at")
            catalog.append(row)
        catalog.sort(
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("game_id") or ""),
            ),
            reverse=True,
        )
        if limit is not None:
            catalog = catalog[:limit]
        return {
            "summary": {
                "generatedAt": summary.get("generated_at"),
                "league": league,
                "team": _normalize_pitching_recap_team(team) or _enterprise_text(team).upper() or None,
                "gameCount": len(catalog),
                "sourceGameCount": _enterprise_int(summary.get("game_count")),
            },
            "games": catalog,
        }

    def _enterprise_pitcher_profiles_payload(
        *,
        league: str,
        team: str | None = None,
        year: str | None = None,
        limit: int = 250,
    ) -> dict[str, Any]:
        summary = _pitching_summary_payload(league=league)
        audit = _pitching_audit_payload(league=league)
        normalized_team = _normalize_pitching_recap_team(team) or _enterprise_text(team).upper()
        normalized_year = _enterprise_text(year)
        games_payload = _enterprise_pitching_games_payload(
            league=league,
            team=normalized_team or None,
            limit=5000,
        )
        games = [
            dict(game)
            for game in games_payload.get("games") or []
            if isinstance(game, dict)
            and (not normalized_year or _enterprise_text(game.get("date")).startswith(normalized_year))
        ]

        windows = [
            dict(window)
            for window in audit.get("decision_windows_all") or []
            if isinstance(window, dict)
            and (not normalized_team or _enterprise_team_match(normalized_team, window.get("decision_team"), window.get("matchup")))
            and (not normalized_year or _enterprise_text(window.get("date")).startswith(normalized_year))
        ]
        calibration = _enterprise_build_runs_saved_calibration(windows)
        projected_by_pitcher_game: dict[tuple[str, str], float] = {}
        for window in windows:
            starter = _coerce_dict(window.get("starter"))
            pitcher_key = _enterprise_text(starter.get("pitcher_id")) or _enterprise_text(starter.get("pitcher_name"))
            game_id = _enterprise_text(window.get("game_id"))
            if not pitcher_key or not game_id:
                continue
            replay_payload = _enterprise_pitching_replay_for_features(game_id, league=league)
            matched_entry = _enterprise_replay_entry_for_window(window, replay_payload)
            components = _enterprise_apply_runs_saved_calibration(
                window,
                _enterprise_projected_runs_components(window, matched_entry),
                calibration,
            )
            projected = _enterprise_number(components.get("projectedRunsSaved"), digits=6)
            if projected is None:
                continue
            key = (pitcher_key, game_id)
            projected_by_pitcher_game[key] = projected_by_pitcher_game.get(key, 0.0) + float(projected)

        official_boxscore_by_game: dict[str, dict[str, Any]] = {}

        def _enterprise_official_boxscore_for_game(game_id: str) -> dict[str, Any]:
            if game_id not in official_boxscore_by_game:
                try:
                    official_boxscore_by_game[game_id] = _load_pitching_official_boxscore(game_id, league=league)
                except Exception:
                    official_boxscore_by_game[game_id] = {}
            return official_boxscore_by_game.get(game_id) or {}

        def _enterprise_pitcher_game_role(game_id: str, pitcher_id: str) -> dict[str, Any]:
            official_boxscore = _enterprise_official_boxscore_for_game(game_id)
            official_row = _coerce_dict(official_boxscore.get(str(pitcher_id)))
            appearance_order = _enterprise_int(official_row.get("appearance_order"))
            role = None
            role_source = "unavailable"
            role_status = "unavailable"
            if appearance_order is not None:
                role = "Starter" if appearance_order == 0 else "Reliever"
                role_source = "statsapi_official_boxscore_pitching_order"
                role_status = "available"
            return {
                "role": role,
                "roleSource": role_source,
                "roleStatus": role_status,
                "teamAppearanceOrder": appearance_order + 1 if appearance_order is not None else None,
                "officialInningsPitchedText": _enterprise_text(official_row.get("ip")) or None,
                "officialInningsPitched": _enterprise_ip_to_float(official_row.get("ip")),
                "officialPitchCount": _enterprise_int(official_row.get("np")),
            }

        game_rows_by_pitcher: dict[str, dict[str, Any]] = {}
        profile_acc: dict[str, dict[str, Any]] = {}
        status_rank = {"STAY": 1, "WATCH": 2, "PREP": 3, "PULL_NOW": 4}
        appearance_facts = _enterprise_appearance_facts_for_games(
            games,
            league=league,
            team=normalized_team or None,
            include_pitch_facts=False,
        )
        workload_by_game_pitcher = {
            (_enterprise_text(row.get("gameId")), _enterprise_text(row.get("pitcherId"))): dict(row)
            for row in _enterprise_reliever_workload_facts(appearance_facts)
            if isinstance(row, dict)
        }
        for appearance in appearance_facts:
            pitcher_id = _enterprise_text(appearance.get("pitcherId"))
            pitcher_name = _enterprise_text(appearance.get("pitcher"), pitcher_id or "Pitcher pending")
            pitcher_key = pitcher_id or pitcher_name
            game_id = _enterprise_text(appearance.get("gameId"))
            if not pitcher_key or not game_id:
                continue
            fielding_team = _enterprise_text(appearance.get("team")).upper()
            role = _enterprise_text(appearance.get("role"))
            role_source = _enterprise_text(appearance.get("roleSource"), "unavailable")
            profile = profile_acc.setdefault(
                pitcher_key,
                {
                    "pitcherId": pitcher_id,
                    "pitcher": pitcher_name,
                    "team": fielding_team,
                    "appearances": set(),
                    "pitchWindows": 0,
                    "degradationSum": 0.0,
                    "degradationCount": 0,
                    "maxDegradation": None,
                    "pullNowGames": set(),
                    "prepOrWatchGames": set(),
                    "projectedRunsSaved": 0.0,
                    "roleCounts": {},
                    "roleSourceCounts": {},
                },
            )
            profile["appearances"].add(game_id)
            if role:
                profile["roleCounts"][role] = int(profile["roleCounts"].get(role) or 0) + 1
                profile["roleSourceCounts"][role_source] = int(profile["roleSourceCounts"].get(role_source) or 0) + 1
            workload = workload_by_game_pitcher.get((game_id, pitcher_id), {})
            game_rows_by_pitcher.setdefault(
                f"{pitcher_key}:{game_id}",
                {
                    "gameId": game_id,
                    "date": appearance.get("date"),
                    "matchup": appearance.get("matchup"),
                    "opponent": appearance.get("opponent"),
                    "pitcher": pitcher_name,
                    "team": fielding_team,
                    "role": appearance.get("role"),
                    "roleSource": appearance.get("roleSource"),
                    "roleStatus": appearance.get("roleStatus"),
                    "teamAppearanceOrder": appearance.get("teamAppearanceOrder"),
                    "officialInningsPitchedText": appearance.get("officialInningsPitchedText"),
                    "officialInningsPitched": appearance.get("officialInningsPitched"),
                    "officialPitchCount": appearance.get("officialPitchCount"),
                    "earnedRuns": appearance.get("earnedRuns"),
                    "runs": appearance.get("runs"),
                    "daysRestBeforeAppearance": workload.get("daysRestBeforeAppearance"),
                    "pitchesLast3Days": workload.get("pitchesLast3Days"),
                    "appearancesLast3Days": workload.get("appearancesLast3Days"),
                    "inningsLast3Days": workload.get("inningsLast3Days"),
                    "backToBack": workload.get("backToBack"),
                    "multiInningRelief": workload.get("multiInningRelief"),
                    "managerAvailabilityProbability": workload.get("managerAvailabilityProbability"),
                    "managerAvailabilityStatus": workload.get("managerAvailabilityStatus"),
                    "managerAvailabilitySource": workload.get("managerAvailabilitySource"),
                    "workloadSource": workload.get("workloadSource"),
                    "rssScore": appearance.get("rssScore"),
                    "rssLabel": appearance.get("rssLabel"),
                    "rssHasMeasurement": appearance.get("rssHasMeasurement"),
                    "rssTriggerLevel": appearance.get("rssTriggerLevel"),
                    "rssTriggerInning": appearance.get("rssTriggerInning"),
                    "rssTriggerPitchCount": appearance.get("rssTriggerPitchCount"),
                    "rssActualExitPitchCount": appearance.get("rssActualExitPitchCount"),
                    "rssSource": appearance.get("rssSource"),
                    "sourceStatus": appearance.get("sourceStatus"),
                    "innings": set(),
                    "pitchWindows": 0,
                    "maxPitchCount": int(appearance.get("officialPitchCount") or 0),
                    "maxDegradation": None,
                    "avgDegradationSum": 0.0,
                    "avgDegradationCount": 0,
                    "peakStatus": "STAY",
                    "stuffByInning": {},
                },
            )
        for game in games:
            game_id = _enterprise_text(game.get("game_id"))
            if not game_id:
                continue
            replay_payload = _enterprise_pitching_replay_for_features(game_id, league=league)
            if not isinstance(replay_payload, dict):
                continue
            home = _enterprise_text(game.get("home_team"))
            away = _enterprise_text(game.get("away_team"))
            opponent = away if normalized_team and normalized_team == home else home
            for entry in replay_payload.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                snapshot = _coerce_dict(entry.get("snapshot"))
                recommendation = _coerce_dict(entry.get("recommendation"))
                state = _coerce_dict(snapshot.get("starter_state"))
                fielding_team = _enterprise_text(snapshot.get("fielding_team")).upper()
                if normalized_team and fielding_team != normalized_team:
                    continue
                pitcher_id = _enterprise_text(snapshot.get("pitcher_id"))
                pitcher_name = _enterprise_text(snapshot.get("pitcher_name"), pitcher_id or "Pitcher pending")
                pitcher_key = pitcher_id or pitcher_name
                if not pitcher_key:
                    continue
                game_key = f"{pitcher_key}:{game_id}"
                role_info = _enterprise_pitcher_game_role(game_id, pitcher_id) if pitcher_id else {
                    "role": None,
                    "roleSource": "unavailable",
                    "roleStatus": "unavailable",
                    "teamAppearanceOrder": None,
                    "officialInningsPitchedText": None,
                    "officialInningsPitched": None,
                    "officialPitchCount": None,
                }
                pitch_count = _enterprise_pitch_count(snapshot, state)
                degradation = _enterprise_number(state.get("degradation_score"), digits=6)
                stuff_score = _enterprise_stuff_score_from_degradation(degradation)
                inning = _enterprise_int(snapshot.get("inning"))
                status = _enterprise_text(recommendation.get("status"), "STAY").upper()
                profile = profile_acc.setdefault(
                    pitcher_key,
                    {
                        "pitcherId": pitcher_id,
                        "pitcher": pitcher_name,
                        "team": fielding_team,
                        "appearances": set(),
                        "pitchWindows": 0,
                        "degradationSum": 0.0,
                        "degradationCount": 0,
                        "maxDegradation": None,
                        "pullNowGames": set(),
                        "prepOrWatchGames": set(),
                        "projectedRunsSaved": 0.0,
                        "roleCounts": {},
                        "roleSourceCounts": {},
                    },
                )
                role = _enterprise_text(role_info.get("role"))
                role_source = _enterprise_text(role_info.get("roleSource"), "unavailable")
                if role and game_key not in game_rows_by_pitcher:
                    profile["roleCounts"][role] = int(profile["roleCounts"].get(role) or 0) + 1
                    profile["roleSourceCounts"][role_source] = int(profile["roleSourceCounts"].get(role_source) or 0) + 1
                profile["appearances"].add(game_id)
                profile["pitchWindows"] += 1
                if degradation is not None:
                    profile["degradationSum"] += float(degradation)
                    profile["degradationCount"] += 1
                    current_max = profile.get("maxDegradation")
                    profile["maxDegradation"] = degradation if current_max is None else max(float(current_max), float(degradation))
                if status == "PULL_NOW":
                    profile["pullNowGames"].add(game_id)
                elif status in {"WATCH", "PREP"}:
                    profile["prepOrWatchGames"].add(game_id)

                game_row = game_rows_by_pitcher.setdefault(
                    game_key,
                    {
                        "gameId": game_id,
                        "date": _enterprise_text(game.get("date")),
                        "matchup": _enterprise_text(game.get("matchup"), f"{away} @ {home}".strip(" @")),
                        "opponent": opponent,
                        "pitcher": pitcher_name,
                        "team": fielding_team,
                        "role": role_info.get("role"),
                        "roleSource": role_info.get("roleSource"),
                        "roleStatus": role_info.get("roleStatus"),
                        "teamAppearanceOrder": role_info.get("teamAppearanceOrder"),
                        "officialInningsPitchedText": role_info.get("officialInningsPitchedText"),
                        "officialInningsPitched": role_info.get("officialInningsPitched"),
                        "officialPitchCount": role_info.get("officialPitchCount"),
                        "innings": set(),
                        "pitchWindows": 0,
                        "maxPitchCount": 0,
                        "maxDegradation": None,
                        "avgDegradationSum": 0.0,
                        "avgDegradationCount": 0,
                        "peakStatus": "STAY",
                        "stuffByInning": {},
                    },
                )
                game_row["pitchWindows"] += 1
                if pitch_count is not None:
                    game_row["maxPitchCount"] = max(int(game_row.get("maxPitchCount") or 0), int(pitch_count))
                if inning is not None:
                    game_row["innings"].add(int(inning))
                    if stuff_score is not None:
                        game_row["stuffByInning"].setdefault(int(inning), []).append(float(stuff_score))
                if degradation is not None:
                    game_row["avgDegradationSum"] += float(degradation)
                    game_row["avgDegradationCount"] += 1
                    current_row_max = game_row.get("maxDegradation")
                    game_row["maxDegradation"] = degradation if current_row_max is None else max(float(current_row_max), float(degradation))
                if status_rank.get(status, 0) > status_rank.get(str(game_row.get("peakStatus") or "STAY"), 0):
                    game_row["peakStatus"] = status

        game_logs_by_pitcher: dict[str, list[dict[str, Any]]] = {}
        for game_key, raw_row in game_rows_by_pitcher.items():
            pitcher_key, game_id = game_key.split(":", 1)
            innings = sorted(int(value) for value in raw_row.get("innings") or [])
            stuff_by_inning = _coerce_dict(raw_row.get("stuffByInning"))
            stuff_curve = [
                round(_enterprise_mean([float(value) for value in values]) or 0.0)
                for inning, values in sorted(stuff_by_inning.items())
                if isinstance(inning, int) or str(inning).isdigit()
                if values
            ]
            avg_deg = None
            if int(raw_row.get("avgDegradationCount") or 0) > 0:
                avg_deg = round(float(raw_row.get("avgDegradationSum") or 0.0) / int(raw_row.get("avgDegradationCount") or 1), 3)
            projected = round(projected_by_pitcher_game.get((pitcher_key, game_id), 0.0), 3)
            if pitcher_key in profile_acc:
                profile_acc[pitcher_key]["projectedRunsSaved"] += projected
            game_logs_by_pitcher.setdefault(pitcher_key, []).append(
                {
                    "gameId": raw_row.get("gameId"),
                    "date": raw_row.get("date"),
                    "matchup": raw_row.get("matchup"),
                    "opponent": raw_row.get("opponent"),
                    "innings": innings,
                    "pitchWindows": int(raw_row.get("pitchWindows") or 0),
                    "maxPitchCount": int(raw_row.get("maxPitchCount") or 0),
                    "role": raw_row.get("role"),
                    "roleSource": raw_row.get("roleSource"),
                    "roleStatus": raw_row.get("roleStatus"),
                    "teamAppearanceOrder": raw_row.get("teamAppearanceOrder"),
                    "officialInningsPitchedText": raw_row.get("officialInningsPitchedText"),
                    "officialInningsPitched": raw_row.get("officialInningsPitched"),
                    "officialPitchCount": raw_row.get("officialPitchCount"),
                    "earnedRuns": raw_row.get("earnedRuns"),
                    "runs": raw_row.get("runs"),
                    "daysRestBeforeAppearance": raw_row.get("daysRestBeforeAppearance"),
                    "pitchesLast3Days": raw_row.get("pitchesLast3Days"),
                    "appearancesLast3Days": raw_row.get("appearancesLast3Days"),
                    "inningsLast3Days": raw_row.get("inningsLast3Days"),
                    "backToBack": raw_row.get("backToBack"),
                    "multiInningRelief": raw_row.get("multiInningRelief"),
                    "managerAvailabilityProbability": raw_row.get("managerAvailabilityProbability"),
                    "managerAvailabilityStatus": raw_row.get("managerAvailabilityStatus"),
                    "managerAvailabilitySource": raw_row.get("managerAvailabilitySource"),
                    "workloadSource": raw_row.get("workloadSource"),
                    "rssScore": raw_row.get("rssScore"),
                    "rssLabel": raw_row.get("rssLabel"),
                    "rssHasMeasurement": raw_row.get("rssHasMeasurement"),
                    "rssTriggerLevel": raw_row.get("rssTriggerLevel"),
                    "rssTriggerInning": raw_row.get("rssTriggerInning"),
                    "rssTriggerPitchCount": raw_row.get("rssTriggerPitchCount"),
                    "rssActualExitPitchCount": raw_row.get("rssActualExitPitchCount"),
                    "rssSource": raw_row.get("rssSource"),
                    "sourceStatus": raw_row.get("sourceStatus"),
                    "peakStatus": raw_row.get("peakStatus"),
                    "maxDegradation": _enterprise_number(raw_row.get("maxDegradation"), digits=3),
                    "avgDegradation": avg_deg,
                    "stuffCurve": stuff_curve,
                    "projectedRunsSaved": projected,
                }
            )

        profiles: list[dict[str, Any]] = []
        for pitcher_key, raw in profile_acc.items():
            game_log = sorted(
                game_logs_by_pitcher.get(pitcher_key, []),
                key=lambda item: (str(item.get("date") or ""), str(item.get("gameId") or "")),
                reverse=True,
            )
            degradation_count = int(raw.get("degradationCount") or 0)
            avg_degradation = (
                round(float(raw.get("degradationSum") or 0.0) / degradation_count, 3)
                if degradation_count > 0
                else None
            )
            role_counts = {
                str(key): int(value)
                for key, value in _coerce_dict(raw.get("roleCounts")).items()
                if str(key) and isinstance(value, int)
            }
            if role_counts:
                primary_role = max(role_counts, key=lambda role: (role_counts[role], role))
                if len(role_counts) > 1:
                    primary_role = "Mixed"
                role_source_counts = _coerce_dict(raw.get("roleSourceCounts"))
                role_source = max(
                    role_source_counts,
                    key=lambda source: (int(role_source_counts.get(source) or 0), str(source)),
                ) if role_source_counts else "unavailable"
            else:
                primary_role = None
                role_source = "unavailable"
            profiles.append(
                {
                    "pitcherId": raw.get("pitcherId"),
                    "pitcher": raw.get("pitcher"),
                    "team": raw.get("team"),
                    "primaryRole": primary_role,
                    "roleSource": role_source,
                    "roleCounts": role_counts,
                    "appearances": len(raw.get("appearances") or []),
                    "pitchWindows": int(raw.get("pitchWindows") or 0),
                    "maxDegradation": _enterprise_number(raw.get("maxDegradation"), digits=3),
                    "avgDegradation": avg_degradation,
                    "pullNowGames": len(raw.get("pullNowGames") or []),
                    "prepOrWatchGames": len(raw.get("prepOrWatchGames") or []),
                    "projectedRunsSaved": round(float(raw.get("projectedRunsSaved") or 0.0), 3),
                    "workloadSummary": _enterprise_workload_summary_from_game_log(game_log),
                    "gameLog": game_log,
                }
            )
        profiles.sort(
            key=lambda item: (
                -float(item.get("projectedRunsSaved") or 0.0),
                -int(item.get("pullNowGames") or 0),
                -float(item.get("maxDegradation") or 0.0),
                str(item.get("pitcher") or ""),
            )
        )
        return {
            "summary": {
                "generatedAt": summary.get("generated_at"),
                "league": league,
                "team": normalized_team or None,
                "year": normalized_year or None,
                "profileCount": len(profiles),
                "gameCount": len(games),
                "officialAppearanceCount": len(appearance_facts),
                "officialReliefAppearanceCount": sum(
                    1 for appearance in appearance_facts if _enterprise_text(appearance.get("role")) == "Reliever"
                ),
                "workloadFactCount": len(workload_by_game_pitcher),
                "rssSignalCount": sum(
                    1 for appearance in appearance_facts if appearance.get("rssScore") is not None
                ),
                "calibrationWindowCount": _enterprise_int(calibration.get("sourceWindowCount")),
            },
            "profiles": profiles[:limit],
        }

    def _enterprise_appearance_workload_payload(
        *,
        league: str,
        team: str | None = None,
        year: str | None = None,
        date_filter: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        summary = _pitching_summary_payload(league=league)
        normalized_team = _normalize_pitching_recap_team(team) or _enterprise_text(team).upper()
        normalized_year = _enterprise_text(year)
        date_text = _enterprise_text(date_filter)
        games_payload = _enterprise_pitching_games_payload(
            league=league,
            team=normalized_team or None,
            date_filter=date_text or None,
            limit=5000,
        )
        games = [
            dict(game)
            for game in games_payload.get("games") or []
            if isinstance(game, dict)
            and (not normalized_year or _enterprise_text(game.get("date")).startswith(normalized_year))
        ]
        # Keep the inspection endpoint bounded when no club/year filter is supplied.
        source_games = games if normalized_team or normalized_year or date_text else games[:250]
        appearances = _enterprise_appearance_facts_for_games(
            source_games,
            league=league,
            team=normalized_team or None,
            include_pitch_facts=bool(date_text),
        )
        workloads = _enterprise_reliever_workload_facts(appearances)
        appearances.sort(
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("gameId") or ""),
                int(item.get("teamAppearanceOrder") or 999),
            ),
            reverse=True,
        )
        workloads.sort(
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("gameId") or ""),
                str(item.get("pitcher") or ""),
            ),
            reverse=True,
        )
        return {
            "summary": {
                "generatedAt": summary.get("generated_at"),
                "league": league,
                "team": normalized_team or None,
                "year": normalized_year or None,
                "date": date_text or None,
                "gameCount": len(source_games),
                "appearanceCount": len(appearances),
                "reliefAppearanceCount": sum(
                    1 for appearance in appearances if _enterprise_text(appearance.get("role")) == "Reliever"
                ),
                "workloadFactCount": len(workloads),
                "rssSignalCount": sum(
                    1 for appearance in appearances if appearance.get("rssScore") is not None
                ),
                "sourceGameCount": _enterprise_int(summary.get("game_count")),
                "sourceStatus": {
                    "officialAppearances": _enterprise_source_status(
                        value=appearances if appearances else None,
                        source="statsapi_official_boxscore",
                        status="available" if appearances else "unavailable",
                    ),
                    "relieverWorkload": _enterprise_source_status(
                        value=workloads if workloads else None,
                        source="statsapi_official_boxscore_appearance_history",
                        status="available" if workloads else "unavailable",
                    ),
                },
            },
            "appearances": appearances[:limit],
            "relieverWorkload": workloads[:limit],
        }

    def _seed_pitching_startup_state() -> None:
        for league in (DEFAULT_PITCHING_LEAGUE, TRIPLE_A_PITCHING_LEAGUE):
            try:
                summary = _get_pitching_summary(league=league)
                status = _load_pitching_refresh_status(league=league)
                STATE.pitching_refresh_status[league] = status
                if summary and str(status.get("status") or "") == "idle":
                    completed = dict(status)
                    completed["status"] = "completed"
                    completed["active"] = False
                    completed["generated_at"] = summary.get("generated_at")
                    completed["snapshot_count"] = summary.get("snapshot_count")
                    completed["game_count"] = summary.get("game_count")
                    STATE.pitching_refresh_status[league] = completed
            except Exception as exc:
                print(f"[abs-modal] pitching startup seed failed for league={league}: {exc}")

    def _refresh_and_persist_model_evaluation(
        *,
        active_policy_version: str,
        active_threshold_profile: str,
        pitch_events_csv_path: str | None,
    ) -> dict[str, Any]:
        return _refresh_and_persist_model_evaluation_artifacts(
            active_policy_version=active_policy_version,
            active_threshold_profile=active_threshold_profile,
            pitch_events_csv_path=pitch_events_csv_path,
            settings=settings,
            repo=repo,
        )

    def _start_background_model_evaluation_refresh(
        *,
        active_policy_version: str,
        active_threshold_profile: str,
        pitch_events_csv_path: str | None,
    ) -> bool:
        existing = _get_model_evaluation_status_snapshot()
        if existing.get("status") == "running":
            return False
        requested_at = _utc_now_iso()
        _set_model_evaluation_status(
            status="running",
            requested_at=requested_at,
        )
        try:
            job = model_evaluation_refresh_job.spawn(
                active_policy_version=active_policy_version,
                active_threshold_profile=active_threshold_profile,
                pitch_events_csv_path=pitch_events_csv_path,
                requested_at=requested_at,
            )
            print(
                "[abs-modal] enqueued model-evaluation refresh job "
                f"policy_version={active_policy_version} threshold_profile={active_threshold_profile} "
                f"call_id={getattr(job, 'object_id', 'unknown')}"
            )
        except Exception as exc:
            _set_model_evaluation_status(
                status="failed",
                completed_at=_utc_now_iso(),
                last_error=str(exc),
            )
            print(f"[abs-modal] failed to enqueue model-evaluation refresh job: {exc}")
            raise
        return True

    def _start_background_recompute(
        active_policy_config: PolicyConfig,
        active_policy_version: str,
        active_threshold_profile: str,
        sims: int,
        seed: int,
        pitch_events_csv_path: str | None,
        artifact_mode: str = ARTIFACT_MODE_FULL_MATRIX,
    ) -> bool:
        mode = _artifact_mode_label(artifact_mode)
        existing = _get_recompute_status_snapshot(mode)
        if existing.get("status") == "running":
            _set_recompute_status(mode, status="running")
            return False

        requested_at = _utc_now_iso()
        _set_recompute_status(
            mode,
            status="running",
            requested_at=requested_at,
        )
        print(f"[abs-modal] starting background stress recompute mode={mode} sims={sims} seed={seed}")
        try:
            job = stress_recompute_job.spawn(
                artifact_mode=mode,
                sims=sims,
                seed=seed,
                pitch_events_csv_path=pitch_events_csv_path,
                threshold_profile=active_threshold_profile,
                policy_version=active_policy_version,
                min_overturn_probability=active_policy_config.min_overturn_probability,
                obvious_miss_distance=active_policy_config.obvious_miss_distance,
                requested_at=requested_at,
            )
            print(
                f"[abs-modal] enqueued stress recompute job mode={mode} sims={sims} seed={seed} "
                f"call_id={getattr(job, 'object_id', 'unknown')}"
            )
        except Exception as exc:
            failed_at = _utc_now_iso()
            _set_recompute_status(
                mode,
                status="failed",
                completed_at=failed_at,
                last_error=str(exc),
            )
            print(f"[abs-modal] failed to enqueue background stress recompute mode={mode}: {exc}")
            raise
        STATE.recompute_futures.pop(mode, None)
        return True

    def _ensure_analysis_artifacts(latest: dict[str, Any] | None) -> dict[str, Any] | None:
        """
        Backfill memo + aptitude artifacts when hydrated rows are summary-only.
        """
        has_top_aptitudes = bool((latest or {}).get("top_aptitudes"))
        has_memo = bool(STATE.latest_memo)
        if has_top_aptitudes and has_memo:
            return latest
        if STATE.backfill_in_progress:
            return latest

        STATE.backfill_in_progress = True
        try:
            # UI artifact regeneration path: keep this fast so Aptitude/Memo don't appear hung.
            for sims in (1, 2):
                try:
                    return _run_and_cache_stress_test(
                        stress_policy_config,
                        settings.abs_stress_policy_version,
                        stress_policy_config.profile_name or settings.abs_stress_threshold_profile,
                        settings,
                        repo,
                        sims=sims,
                        seed=26,
                        pitch_events_csv_path=settings.pitch_events_csv_path,
                    )
                except Exception as exc:
                    print(f"[abs-modal] analysis artifact backfill failed at sims={sims}: {exc}")
            return latest
        finally:
            STATE.backfill_in_progress = False

    @api.post("/v1/recommend")
    def recommend(payload: RecommendationRequestModel) -> dict[str, object]:
        try:
            active_service = _require_service()
            request = RecommendationRequest(
                challenge_context=ChallengeContext(**payload.challenge_context.model_dump()),
                pitch_observation=PitchObservation(**payload.pitch_observation.model_dump()),
                model_version=payload.model_version,
            )
            result = active_service.recommend(request, signal_version=settings.abs_signal_version)
            try:
                repo.log_recommendation(
                    {
                        "request": payload.model_dump(),
                        "response": result,
                        "recommendation": result["recommendation"],
                        "confidence": result["confidence"],
                        "net_ev": result["net_ev"],
                        "dugout_signal": result["dugout_signal"],
                        "latency_ms": result["latency_ms"],
                        "model_version_id": settings.abs_policy_version,
                    }
                )
            except Exception:
                pass
            _log_decision_telemetry_safe(
                repo,
                {
                    "pitch_id": payload.pitch_observation.pitch_id,
                    "game_id": payload.challenge_context.game_id,
                    "recommended_action": result["recommendation"],
                    "recommended_challenger_role": result.get("recommended_challenger_role"),
                    "model_version": result.get("core_model_version") or settings.abs_core_model_version,
                    "policy_version": result.get("policy_version") or settings.abs_policy_version,
                    "player_action": None,
                    "actual_challenger_role": None,
                    "outcome": None,
                    "followed_recommendation": None,
                    "challenge_latency_ms": result.get("latency_ms"),
                    "context_snapshot": {
                        "telemetry_source": "recommend",
                        "requested_at": _utc_now_iso(),
                        "request": payload.model_dump(),
                        "model_outputs": {
                            "recommendation": result.get("recommendation"),
                            "dugout_signal": result.get("dugout_signal"),
                            "confidence": result.get("confidence"),
                            "p_overturn": result.get("p_overturn"),
                            "run_swing": result.get("run_swing"),
                            "net_ev": result.get("net_ev"),
                            "immediate_overturn_ev": result.get("immediate_overturn_ev"),
                            "state_leverage_adjustment": result.get("state_leverage_adjustment"),
                            "opportunity_cost": result.get("opportunity_cost"),
                            "top_drivers": result.get("top_drivers"),
                        },
                    },
                },
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.get("/v1/recommend/presets")
    def recommend_presets(limit: int = Query(default=6, ge=2, le=20)) -> list[dict[str, object]]:
        try:
            active_service = _require_service()
            presets = _build_recommendation_presets(active_service, limit=limit)
            try:
                repo.upsert_presets(presets)
            except Exception:
                pass
            return presets
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @api.get("/v1/games")
    def games(
        limit: int | None = Query(default=None, ge=1, le=5000),
        rank_by: str = Query(default="recent", pattern="^(recent|expected_edge|demo_ready)$"),
        scope: str = Query(default="abs_only", pattern="^(abs_only|all)$"),
    ) -> list[dict[str, Any]]:
        resolved_scope = _resolve_replay_scope(scope)
        if rank_by == "recent":
            catalog = _build_games_catalog_base_from_csv(resolved_scope)
        else:
            try:
                catalog = _build_games_catalog(resolved_scope, rank_by=rank_by)
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
                print(
                    f"[abs-modal] ranked catalog unavailable for scope={resolved_scope} rank_by={rank_by}; "
                    "falling back to recent catalog"
                )
                catalog = _build_games_catalog_base_from_csv(resolved_scope)
        return catalog if limit is None else catalog[:limit]

    @api.post("/v1/replay/refresh")
    def replay_refresh(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        resolved_scope = _resolve_replay_scope(str(body.get("scope") or settings.abs_replay_scope_default))
        start_date = str(body.get("start_date") or "").strip() or None
        end_date = str(body.get("end_date") or "").strip() or None
        background = _coerce_boolish(body.get("background", True))
        if background:
            refresh_meta = _start_background_replay_refresh(
                scope=resolved_scope,
                start_date=start_date,
                end_date=end_date,
            )
            return _build_replay_refresh_response(resolved_scope, refresh_meta)
        refresh_meta = _refresh_replay_scope(
            scope=resolved_scope,
            start_date=start_date,
            end_date=end_date,
        )
        return _build_replay_refresh_response(resolved_scope, refresh_meta)

    @api.get("/v1/replay/refresh")
    def replay_refresh_get(
        scope: str = Query(default="abs_only", pattern="^(abs_only|all)$"),
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
        background: bool = Query(default=True),
    ) -> dict[str, Any]:
        # Backwards-compatibility for stale clients that still call refresh via GET.
        resolved_scope = _resolve_replay_scope(scope)
        if background:
            refresh_meta = _start_background_replay_refresh(
                scope=resolved_scope,
                start_date=start_date,
                end_date=end_date,
            )
            return _build_replay_refresh_response(resolved_scope, refresh_meta)
        refresh_meta = _refresh_replay_scope(
            scope=resolved_scope,
            start_date=start_date,
            end_date=end_date,
        )
        return _build_replay_refresh_response(resolved_scope, refresh_meta)

    @api.get("/v1/replay/{game_id}")
    def replay_game(
        game_id: str,
        scope: str = Query(default="abs_only", pattern="^(abs_only|all)$"),
        policy_team: str | None = Query(default=None),
    ) -> dict[str, Any]:
        resolved_scope = _resolve_replay_scope(scope)
        if str(game_id).strip().lower() == "refresh":
            refresh_meta = _start_background_replay_refresh(scope=resolved_scope)
            return _build_replay_refresh_response(resolved_scope, refresh_meta)
        active_service = _require_replay_service(resolved_scope)
        payload = _build_replay_payload(
            resolved_scope,
            active_service,
            game_id=str(game_id),
            policy_team_override=policy_team,
        )
        _log_decision_telemetry_safe(
            repo,
            _build_replay_decision_telemetry_rows(
                scope=resolved_scope,
                active_service=active_service,
                game_id=str(game_id),
                replay_payload=payload,
            ),
        )
        return payload

    @api.post("/v1/pitching/refresh")
    def pitching_refresh(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        try:
            league = _normalize_pitching_league(body.get("league"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        background = _coerce_boolish(body.get("background", True))
        start_date = str(body.get("start_date") or "").strip() or None
        end_date = str(body.get("end_date") or "").strip() or None
        if background:
            return _build_pitching_refresh_response(
                _start_background_pitching_refresh(
                    league=league,
                    start_date=start_date,
                    end_date=end_date,
                ),
                league=league,
            )
        return _build_pitching_refresh_response(
            _refresh_pitching_artifacts(
                settings,
                league=league,
                start_date=start_date,
                end_date=end_date,
            ),
            league=league,
        )

    @api.get("/v1/pitching/refresh")
    def pitching_refresh_get(
        background: bool = Query(default=True),
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
    ) -> dict[str, Any]:
        if background:
            return _build_pitching_refresh_response(
                _start_background_pitching_refresh(
                    league=league,
                    start_date=start_date,
                    end_date=end_date,
                ),
                league=league,
            )
        return _build_pitching_refresh_response(
            _refresh_pitching_artifacts(
                settings,
                league=league,
                start_date=start_date,
                end_date=end_date,
            ),
            league=league,
        )

    @api.post("/v1/data/sync")
    @api.get("/v1/data/sync")
    def data_sync_trigger(force_start_date: str | None = Query(default=None)) -> dict[str, Any]:
        existing = _load_data_sync_status()
        if existing.get("active"):
            return existing
        requested_at = _utc_now_iso()
        running = _default_data_sync_status()
        # Preserve the stored last_sync_date so the job doesn't re-download old data
        if existing.get("last_sync_date"):
            running["last_sync_date"] = existing["last_sync_date"]
        running.update({"status": "running", "active": True, "requested_at": requested_at})
        _persist_data_sync_status(running)
        try:
            data_sync_job.spawn(requested_at=requested_at, force_start_date=force_start_date)
        except Exception as exc:
            failed = _default_data_sync_status()
            failed.update({"status": "failed", "active": False, "last_error": str(exc)})
            _persist_data_sync_status(failed)
            raise HTTPException(status_code=503, detail=str(exc))
        return running

    @api.get("/v1/data/sync/status")
    def data_sync_status() -> dict[str, Any]:
        return _load_data_sync_status()

    @api.post("/v1/abs-challenge/statsapi-refresh")
    @api.get("/v1/abs-challenge/statsapi-refresh")
    def abs_challenge_statsapi_refresh_trigger() -> dict[str, Any]:
        existing = _load_statsapi_refresh_status()
        if existing.get("active"):
            return existing
        requested_at = _utc_now_iso()
        running = _default_statsapi_refresh_status()
        running.update({"status": "running", "active": True, "requested_at": requested_at})
        _persist_statsapi_refresh_status(running)
        try:
            abs_challenge_statsapi_refresh_job.spawn(requested_at=requested_at)
        except Exception as exc:
            failed = _default_statsapi_refresh_status()
            failed.update({"status": "failed", "active": False, "last_error": str(exc)})
            _persist_statsapi_refresh_status(failed)
            raise HTTPException(status_code=503, detail=str(exc))
        return running

    @api.get("/v1/abs-challenge/statsapi-refresh/status")
    def abs_challenge_statsapi_refresh_status() -> dict[str, Any]:
        return _load_statsapi_refresh_status()

    @api.get("/v1/pitching/status")
    def pitching_status(
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        snapshot = _load_pitching_refresh_status(league=league)
        summary = _get_pitching_summary(league=league) or {}
        if summary:
            if snapshot.get("generated_at") is None:
                snapshot["generated_at"] = summary.get("generated_at")
            if snapshot.get("snapshot_count") is None:
                snapshot["snapshot_count"] = summary.get("snapshot_count")
            if snapshot.get("game_count") is None:
                snapshot["game_count"] = summary.get("game_count")
            if snapshot.get("status") == "idle":
                snapshot["status"] = "completed"
        snapshot["league"] = league
        return snapshot

    @api.get("/v1/pitching/summary")
    def pitching_summary(
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        return _pitching_summary_payload(league=league)

    @api.post("/v1/pitching/calibration/run")
    def pitching_calibration_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        season = int(body.get("season") or 2026)
        background = _coerce_boolish(body.get("background", True))
        start_date = str(body.get("start_date") or "").strip() or None
        end_date = str(body.get("end_date") or "").strip() or None
        game_type = str(body.get("game_type") or "R").strip().upper() or "R"
        min_pitch_count = body.get("min_pitch_count")
        resolved_min_pitch_count = int(min_pitch_count) if min_pitch_count is not None else None
        upload_outputs = _coerce_boolish(body.get("upload_outputs", True))
        if background:
            snapshot = _start_background_pitching_calibration(
                season=season,
                start_date=start_date,
                end_date=end_date,
                game_type=game_type,
                min_pitch_count=resolved_min_pitch_count,
                upload_outputs=upload_outputs,
            )
            return _build_pitching_calibration_response(snapshot, season=season)
        return _build_pitching_calibration_response(
            _run_pitching_calibration(
                settings,
                season=season,
                start_date=start_date,
                end_date=end_date,
                game_type=game_type,
                min_pitch_count=resolved_min_pitch_count,
                upload_outputs=upload_outputs,
            ),
            season=season,
        )

    @api.get("/v1/pitching/calibration/run")
    def pitching_calibration_run_get(
        season: int = Query(default=2026, ge=2020, le=2035),
        background: bool = Query(default=True),
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
        game_type: str = Query(default="R"),
        min_pitch_count: int | None = Query(default=None, ge=1, le=200),
        upload_outputs: bool = Query(default=True),
    ) -> dict[str, Any]:
        if background:
            snapshot = _start_background_pitching_calibration(
                season=season,
                start_date=start_date,
                end_date=end_date,
                game_type=game_type,
                min_pitch_count=min_pitch_count,
                upload_outputs=upload_outputs,
            )
            return _build_pitching_calibration_response(snapshot, season=season)
        return _build_pitching_calibration_response(
            _run_pitching_calibration(
                settings,
                season=season,
                start_date=start_date,
                end_date=end_date,
                game_type=game_type,
                min_pitch_count=min_pitch_count,
                upload_outputs=upload_outputs,
            ),
            season=season,
        )

    @api.get("/v1/pitching/calibration/status")
    def pitching_calibration_status(
        season: int = Query(default=2026, ge=2020, le=2035),
    ) -> dict[str, Any]:
        return _build_pitching_calibration_response(
            _load_pitching_calibration_status(season=season),
            season=season,
        )

    @api.get("/v1/pitching/calibration/latest")
    def pitching_calibration_latest(
        season: int = Query(default=2026, ge=2020, le=2035),
    ) -> dict[str, Any]:
        payload = _pitching_store_get(_pitching_calibration_latest_key(season=season))
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="Pitching calibration output unavailable. Run /v1/pitching/calibration/run first.")
        return payload

    @api.post("/v1/pitching/preventable-runs/model/run")
    def pitching_preventable_runs_model_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        season = int(body.get("season") or 2026)
        background = _coerce_boolish(body.get("background", True))
        training_start_date = str(body.get("training_start_date") or "").strip() or None
        training_end_date = str(body.get("training_end_date") or "").strip() or None
        holdout_start_date = str(body.get("holdout_start_date") or "").strip() or None
        holdout_end_date = str(body.get("holdout_end_date") or "").strip() or None
        game_type = str(body.get("game_type") or "R").strip().upper() or "R"
        min_pitch_count = body.get("min_pitch_count")
        resolved_min_pitch_count = int(min_pitch_count) if min_pitch_count is not None else None
        upload_outputs = _coerce_boolish(body.get("upload_outputs", True))
        if background:
            snapshot = _start_background_pitching_preventable_runs_model(
                season=season,
                training_start_date=training_start_date,
                training_end_date=training_end_date,
                holdout_start_date=holdout_start_date,
                holdout_end_date=holdout_end_date,
                game_type=game_type,
                min_pitch_count=resolved_min_pitch_count,
                upload_outputs=upload_outputs,
            )
            return _build_pitching_preventable_model_response(snapshot, season=season)
        return _build_pitching_preventable_model_response(
            _run_pitching_preventable_runs_model(
                settings,
                season=season,
                training_start_date=training_start_date,
                training_end_date=training_end_date,
                holdout_start_date=holdout_start_date,
                holdout_end_date=holdout_end_date,
                game_type=game_type,
                min_pitch_count=resolved_min_pitch_count,
                upload_outputs=upload_outputs,
            ),
            season=season,
        )

    @api.get("/v1/pitching/preventable-runs/model/run")
    def pitching_preventable_runs_model_run_get(
        season: int = Query(default=2026, ge=2020, le=2035),
        background: bool = Query(default=True),
        training_start_date: str | None = Query(default=None),
        training_end_date: str | None = Query(default=None),
        holdout_start_date: str | None = Query(default=None),
        holdout_end_date: str | None = Query(default=None),
        game_type: str = Query(default="R"),
        min_pitch_count: int | None = Query(default=None, ge=1, le=200),
        upload_outputs: bool = Query(default=True),
    ) -> dict[str, Any]:
        if background:
            snapshot = _start_background_pitching_preventable_runs_model(
                season=season,
                training_start_date=training_start_date,
                training_end_date=training_end_date,
                holdout_start_date=holdout_start_date,
                holdout_end_date=holdout_end_date,
                game_type=game_type,
                min_pitch_count=min_pitch_count,
                upload_outputs=upload_outputs,
            )
            return _build_pitching_preventable_model_response(snapshot, season=season)
        return _build_pitching_preventable_model_response(
            _run_pitching_preventable_runs_model(
                settings,
                season=season,
                training_start_date=training_start_date,
                training_end_date=training_end_date,
                holdout_start_date=holdout_start_date,
                holdout_end_date=holdout_end_date,
                game_type=game_type,
                min_pitch_count=min_pitch_count,
                upload_outputs=upload_outputs,
            ),
            season=season,
        )

    @api.get("/v1/pitching/preventable-runs/model/status")
    def pitching_preventable_runs_model_status(
        season: int = Query(default=2026, ge=2020, le=2035),
    ) -> dict[str, Any]:
        return _build_pitching_preventable_model_response(
            _load_pitching_preventable_model_status(season=season),
            season=season,
        )

    @api.get("/v1/pitching/preventable-runs/model/latest")
    def pitching_preventable_runs_model_latest(
        season: int = Query(default=2026, ge=2020, le=2035),
    ) -> dict[str, Any]:
        payload = _pitching_store_get(_pitching_preventable_model_latest_key(season=season))
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=404,
                detail="Preventable-runs calibration model unavailable. Run /v1/pitching/preventable-runs/model/run first.",
            )
        return payload

    @api.get("/v1/pitching/preventable-runs/opportunities")
    def pitching_preventable_runs_opportunities(
        season: int = Query(default=2026, ge=2020, le=2035),
        team: str | None = Query(default=None),
        game_id: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=5000),
        scope: str = Query(default="top", pattern="^(top|game_matrix|all_games)$"),
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        payload = _pitching_store_get(_pitching_preventable_model_latest_key(season=season))
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=404,
                detail="Preventable-runs opportunities unavailable. Run /v1/pitching/preventable-runs/model/run first.",
            )
        opportunities = payload.get("opportunities") if isinstance(payload.get("opportunities"), dict) else {}
        normalized_team = str(team or "").strip().upper()
        matrix_scope = scope in {"game_matrix", "all_games"}
        if normalized_team:
            source_key = "teamGameMatrix" if matrix_scope else "teamTop"
            rows = list(((opportunities.get(source_key) or {}).get(normalized_team) or []))
            if matrix_scope and not rows:
                rows = list(((opportunities.get("teamTop") or {}).get(normalized_team) or []))
            team_summary = (opportunities.get("teamSummary") or {}).get(normalized_team)
        else:
            rows = list(opportunities.get("globalTop") or [])
            team_summary = None
        normalized_league = _normalize_pitching_league(league)
        requested_game_id = str(game_id or "").strip()
        if requested_game_id and normalized_team:
            replay_payload = _get_pitching_replay(requested_game_id, league=normalized_league)
            if isinstance(replay_payload, dict):
                game = replay_payload.get("game") if isinstance(replay_payload.get("game"), dict) else {}
                exact_lookup = _pitching_recap_preventable_lookup(
                    {
                        "game_id": requested_game_id,
                        "date": str(game.get("date") or f"{season}-01-01"),
                    },
                    normalized_team,
                    league=normalized_league,
                    replay_payload=replay_payload,
                )
                keyed_rows: dict[tuple[str, str, int | None], dict[str, Any]] = {}
                for row in exact_lookup.values():
                    if not isinstance(row, dict):
                        continue
                    row_game_id = str(row.get("gameId") or row.get("game_id") or "")
                    row_pitcher_id = str(row.get("pitcherId") or row.get("pitcher_id") or "")
                    if row_game_id != requested_game_id or not row_pitcher_id:
                        continue
                    try:
                        row_pitch_count = int(float(row.get("pitchCount"))) if row.get("pitchCount") is not None else None
                    except Exception:
                        row_pitch_count = None
                    keyed_rows[(row_game_id, row_pitcher_id, row_pitch_count)] = row
                exact_rows = list(keyed_rows.values())
                exact_rows.sort(
                    key=lambda row: (
                        float(row.get("projectedPreventableRuns") or row.get("modelImpliedRunsSaved") or 0.0),
                        int(row.get("pitchCount") or 0),
                    ),
                    reverse=True,
                )
                if exact_rows:
                    merged: dict[tuple[str, str, int | None], dict[str, Any]] = {}
                    for row in [*exact_rows, *rows]:
                        if not isinstance(row, dict):
                            continue
                        row_game_id = str(row.get("gameId") or row.get("game_id") or "")
                        row_pitcher_id = str(row.get("pitcherId") or row.get("pitcher_id") or "")
                        try:
                            row_pitch_count = int(float(row.get("pitchCount"))) if row.get("pitchCount") is not None else None
                        except Exception:
                            row_pitch_count = None
                        merged.setdefault((row_game_id, row_pitcher_id, row_pitch_count), row)
                    rows = list(merged.values())
        rows = [
            {
                **row,
                "allocationBucket": _preventable_runs_game_bucket(row),
            }
            if isinstance(row, dict)
            else row
            for row in rows
        ]
        display_rows = [dict(row) for row in rows[:limit] if isinstance(row, dict)]
        replay_cache: dict[str, dict[str, Any] | None] = {}
        if normalized_team or requested_game_id:
            enriched_rows: list[dict[str, Any]] = []
            for row in display_rows:
                row_game_id = _enterprise_text(
                    _enterprise_first_present(
                        row.get("gameId"),
                        row.get("game_id"),
                        row.get("gamePk"),
                        row.get("game_pk"),
                        requested_game_id,
                    )
                )
                replay_payload = None
                if row_game_id:
                    if row_game_id not in replay_cache:
                        try:
                            replay_cache[row_game_id] = _get_pitching_replay(row_game_id, league=normalized_league)
                        except Exception:
                            replay_cache[row_game_id] = None
                    replay_payload = replay_cache.get(row_game_id)
                enriched_rows.append(_preventable_runs_enrich_display_fields(row, replay_payload))
            display_rows = enriched_rows
        definitions = dict(opportunities.get("definitions") or {})
        definitions["teamGameMatrixCriteria"] = (
            "Starter late-inning stuff is above average when normalized degradation is below 0.45; "
            "bullpen quality is above average when the best available reliever net-option score is at least 0.65. "
            "standard=(starter above, bullpen above), tandem=(starter below, bullpen above), "
            "push=(starter above, bullpen below), workload=(starter below, bullpen below)."
        )
        return {
            "generated_at": payload.get("generated_at"),
            "season": season,
            "team": normalized_team or None,
            "game_id": requested_game_id or None,
            "scope": scope,
            "model_status": ((payload.get("model") or {}).get("status") if isinstance(payload.get("model"), dict) else None),
            "training_start_date": payload.get("training_start_date"),
            "training_end_date": payload.get("training_end_date"),
            "holdout_start_date": payload.get("holdout_start_date"),
            "holdout_end_date": payload.get("holdout_end_date"),
            "status": opportunities.get("status") or "unavailable",
            "summary": team_summary,
            "teamSummary": opportunities.get("teamSummary") if not normalized_team else None,
            "teamGameMatrix": opportunities.get("teamGameMatrix") if not normalized_team else None,
            "pitcherSummaryTop": opportunities.get("pitcherSummaryTop") if not normalized_team else None,
            "rows": display_rows,
            "definitions": definitions,
        }

    @api.get("/v1/pitching/games")
    def pitching_games(
        limit: int | None = Query(default=None, ge=1, le=5000),
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> list[dict[str, Any]]:
        summary = _pitching_summary_payload(league=league)
        games = _get_pitching_games(league=league)
        if not games:
            summary_game_count = summary.get("game_count")
            if summary_game_count is not None and int(summary_game_count or 0) <= 0:
                return []
            raise HTTPException(
                status_code=503,
                detail=(
                    "Pitching games catalog unavailable even though a summary exists. "
                    "Run /v1/pitching/refresh again."
                ),
            )
        catalog = [dict(item) for item in games]
        catalog.sort(
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("game_id") or ""),
            ),
            reverse=True,
        )
        for item in catalog:
            item["generated_at"] = summary.get("generated_at")
        return catalog if limit is None else catalog[:limit]

    @api.get("/v1/pitching/replay/{game_id}")
    def pitching_replay(
        game_id: str,
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        _pitching_summary_payload(league=league)
        payload = _get_pitching_replay(str(game_id), league=league)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"Pitching replay for game {game_id} not found")
        return payload

    @api.get("/v1/pitching/recap/{game_id}")
    def pitching_recap(
        game_id: str,
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        payload = _get_pitching_replay(str(game_id), league=league)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"No replay data for game {game_id}")
        return _build_game_recap(payload, league=league)

    @api.get("/v1/pitching/recap-settings")
    def pitching_recap_settings_get(
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        return _pitching_recap_settings_public_payload(
            _get_pitching_recap_settings(league=league),
            league=league,
        )

    @api.post("/v1/pitching/recap-settings")
    async def pitching_recap_settings_post(
        request: Request,
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        payload = await request.json()
        saved = _save_pitching_recap_settings(payload if isinstance(payload, dict) else {}, league=league)
        return _pitching_recap_settings_public_payload(saved, league=league)

    @api.post("/v1/pitching/recap-email")
    async def pitching_recap_email(
        request: Request,
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="Invalid recap email payload")
        game_id = str(payload.get("game_id") or "").strip()
        team = str(payload.get("team") or "").strip()
        recipient = str(payload.get("recipient") or "").strip() or None
        send = bool(payload.get("send"))
        if not game_id:
            raise HTTPException(status_code=422, detail="game_id is required")
        return _build_pitching_recap_email_result(
            game_id=game_id,
            team=team,
            league=league,
            recipient_override=recipient,
            send=send,
        )

    @api.get("/v1/pitching/share/grant/{grant_id}")
    def pitching_share_grant(grant_id: str) -> dict[str, Any]:
        record = _require_replay_share(grant_id, active_only=False)
        return _pitching_replay_share_public_payload(record)

    @api.post("/v1/pitching/share/grant/{grant_id}/login")
    def pitching_share_grant_login(grant_id: str) -> dict[str, Any]:
        record = _require_replay_share(grant_id)
        last_sent_at = _parse_iso_datetime(str(record.get("last_login_email_sent_at") or ""))
        if last_sent_at is not None:
            seconds_since_last_send = (datetime.now(timezone.utc) - last_sent_at).total_seconds()
            if seconds_since_last_send < 60:
                raise HTTPException(status_code=429, detail="Secure access link already sent recently. Please wait one minute.")
        _send_replay_share_login_email(record)
        record["last_login_email_sent_at"] = _utc_now_iso()
        put_pitching_replay_share_grant(grant_id, record)
        return {
            "ok": True,
            "grant": _pitching_replay_share_public_payload(record),
            "sent_to": mask_email(record.get("recipient_email")),
        }

    @api.get("/v1/pitching/share/grant/{grant_id}/bundle")
    def pitching_share_grant_bundle(grant_id: str, request: Request) -> dict[str, Any]:
        record = _require_replay_share(grant_id)
        signed_in_email = _authenticated_email(request)
        if signed_in_email != normalize_email(record.get("recipient_email")):
            raise HTTPException(status_code=403, detail="This replay grant belongs to a different email address")
        game_id = str(record.get("game_id") or "").strip()
        record_league = _normalize_pitching_league(record.get("league"))
        payload = _get_pitching_replay(game_id, league=record_league)
        if payload is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Replay for game {game_id} is still syncing into pitching artifacts. "
                    "Refresh pitching artifacts, then regenerate or resend the recap."
                ),
            )
        record["last_accessed_at"] = _utc_now_iso()
        put_pitching_replay_share_grant(grant_id, record)
        return {
            "grant": _pitching_replay_share_public_payload(record),
            "replay": payload,
            "recap": _build_game_recap(payload, league=record_league),
        }

    @api.get("/v1/pitching/audit/summary")
    def pitching_audit_summary(
        limit: int = Query(default=15, ge=1, le=1000),
        team: str | None = Query(default=None),
        leverage_band: str | None = Query(default=None, pattern="^(ROUTINE|ELEVATED|HIGH)$"),
        status: str | None = Query(default=None, pattern="^(STAY|WATCH|PREP|PULL_NOW)$"),
        actual_outcome: str | None = Query(default=None, pattern="^(changed|stayed)$"),
        year: str | None = Query(default=None, pattern="^[0-9]{4}$"),
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        return filter_pitching_audit_summary(
            _pitching_audit_payload(league=league),
            limit=limit,
            team=team,
            leverage_band=leverage_band,
            status=status,
            actual_outcome=actual_outcome,
            year=year,
        )

    @api.get("/v1/enterprise/run-saving/board")
    def enterprise_run_saving_board(
        limit: int = Query(default=12, ge=1, le=50),
        team: str | None = Query(default=None),
        date: str | None = Query(default=None, pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$"),
        year: str | None = Query(default=None, pattern="^[0-9]{4}$"),
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        return _enterprise_run_saving_board_payload(
            league=league,
            limit=limit,
            team=team,
            date_filter=date,
            year=year,
        )

    @api.get("/v1/enterprise/run-saving/games")
    def enterprise_run_saving_games(
        limit: int | None = Query(default=250, ge=1, le=5000),
        team: str | None = Query(default=None),
        date: str | None = Query(default=None, pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$"),
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        return _enterprise_pitching_games_payload(
            league=league,
            team=team,
            date_filter=date,
            limit=limit,
        )

    @api.get("/v1/enterprise/run-saving/pitcher-profiles")
    def enterprise_run_saving_pitcher_profiles(
        limit: int = Query(default=250, ge=1, le=750),
        team: str | None = Query(default=None),
        year: str | None = Query(default=None, pattern="^[0-9]{4}$"),
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        return _enterprise_pitcher_profiles_payload(
            league=league,
            team=team,
            year=year,
            limit=limit,
        )

    @api.get("/v1/enterprise/run-saving/appearances")
    def enterprise_run_saving_appearances(
        limit: int = Query(default=500, ge=1, le=5000),
        team: str | None = Query(default=None),
        year: str | None = Query(default=None, pattern="^[0-9]{4}$"),
        date: str | None = Query(default=None, pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$"),
        league: str = Query(default=DEFAULT_PITCHING_LEAGUE, pattern="^(mlb|triple_a)$"),
    ) -> dict[str, Any]:
        return _enterprise_appearance_workload_payload(
            league=league,
            team=team,
            year=year,
            date_filter=date,
            limit=limit,
        )

    @api.post("/v1/stress-test/run")
    @api.post("/v1/stress-test/run/")
    def stress_test_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        force = bool(body.get("force", False))
        sims_raw = body.get("sims")
        seed = int(body.get("seed", settings.abs_intraday_seed))
        path = body.get("pitch_events_csv_path")
        artifact_mode_override = str(body.get("artifact_mode") or "").strip() or None
        threshold_profile_override = str(body.get("threshold_profile") or "").strip() or None
        policy_version_override = str(body.get("policy_version") or "").strip() or None
        min_overturn_probability = body.get("min_overturn_probability")
        obvious_miss_distance = body.get("obvious_miss_distance")
        active_stress_policy = _policy_config_with_overrides(
            stress_policy_config,
            threshold_profile=threshold_profile_override,
            min_overturn_probability=(
                float(min_overturn_probability)
                if min_overturn_probability is not None and str(min_overturn_probability).strip() != ""
                else None
            ),
            obvious_miss_distance=(
                float(obvious_miss_distance)
                if obvious_miss_distance is not None and str(obvious_miss_distance).strip() != ""
                else None
            ),
        )
        active_stress_policy_version = policy_version_override or settings.abs_stress_policy_version
        requested_artifact_mode = (
            artifact_mode_override
            if artifact_mode_override in {ARTIFACT_MODE_FAST_BASE, ARTIFACT_MODE_FULL_MATRIX}
            else ARTIFACT_MODE_FAST_BASE
        )

        if sims_raw is None and not force and (path is None or str(path).strip() == ""):
            _start_background_recompute(
                active_stress_policy,
                active_stress_policy_version,
                active_stress_policy.profile_name or threshold_profile_override or settings.abs_stress_threshold_profile,
                sims=_fast_base_sims(settings) if requested_artifact_mode == ARTIFACT_MODE_FAST_BASE else settings.abs_intraday_sims,
                seed=seed,
                pitch_events_csv_path=path,
                artifact_mode=requested_artifact_mode,
            )
            row = _get_latest_stress_row_with_timeout(timeout_seconds=3.0)
            if row:
                try:
                    return _hydrate_stress_result_from_row(row)
                except Exception as exc:
                    print(f"[abs-modal] failed to hydrate persisted stress result in /v1/stress-test/run: {exc}")
            if STATE.latest_result is not None:
                return STATE.latest_result
            raise HTTPException(
                status_code=503,
                detail=(
                    "Latest stress-test artifact unavailable right now. "
                    "Try /v1/stress-test/latest or rerun with explicit sims once backend load stabilizes."
                ),
            )

        sims = int(sims_raw if sims_raw is not None else settings.abs_intraday_sims)
        sims = max(1, min(sims, 500))
        return _run_and_cache_stress_test(
            active_stress_policy,
            active_stress_policy_version,
            active_stress_policy.profile_name or threshold_profile_override or settings.abs_stress_threshold_profile,
            settings,
            repo,
            sims=sims,
            seed=seed,
            pitch_events_csv_path=path,
            artifact_mode=ARTIFACT_MODE_FULL_MATRIX if force or sims_raw is not None else requested_artifact_mode,
            reference_full_row=(
                _get_latest_full_matrix_stress_row_with_timeout(timeout_seconds=2.0)
                if requested_artifact_mode == ARTIFACT_MODE_FAST_BASE
                else None
            ),
        )

    @api.get("/v1/stress-test/recompute")
    def stress_test_recompute(
        sims: int | None = Query(default=None, ge=1, le=500),
        seed: int | None = Query(default=None, ge=0, le=1_000_000_000),
        pitch_events_csv_path: str | None = Query(default=None),
        background: bool = Query(default=True),
        artifact_mode: str | None = Query(default=None, pattern="^(fast_base|full_matrix)$"),
        threshold_profile: str | None = Query(default=None),
        policy_version: str | None = Query(default=None),
        min_overturn_probability: float | None = Query(default=None),
        obvious_miss_distance: float | None = Query(default=None),
    ) -> dict[str, Any]:
        requested_artifact_mode = artifact_mode or (ARTIFACT_MODE_FULL_MATRIX if sims is not None else ARTIFACT_MODE_FAST_BASE)
        default_sims = _fast_base_sims(settings) if requested_artifact_mode == ARTIFACT_MODE_FAST_BASE else settings.abs_intraday_sims
        resolved_sims = int(sims if sims is not None else default_sims)
        resolved_seed = int(seed if seed is not None else settings.abs_intraday_seed)
        active_stress_policy = _policy_config_with_overrides(
            stress_policy_config,
            threshold_profile=threshold_profile,
            min_overturn_probability=min_overturn_probability,
            obvious_miss_distance=obvious_miss_distance,
        )
        active_stress_policy_version = policy_version or settings.abs_stress_policy_version
        if not background:
            return _run_and_cache_stress_test(
                active_stress_policy,
                active_stress_policy_version,
                active_stress_policy.profile_name or threshold_profile or settings.abs_stress_threshold_profile,
                settings,
                repo,
                sims=resolved_sims,
                seed=resolved_seed,
                pitch_events_csv_path=pitch_events_csv_path,
                artifact_mode=requested_artifact_mode,
                reference_full_row=(
                    _get_latest_full_matrix_stress_row_with_timeout(timeout_seconds=2.0)
                    if requested_artifact_mode == ARTIFACT_MODE_FAST_BASE
                    else None
                ),
            )

        _start_background_recompute(
            active_stress_policy,
            active_stress_policy_version,
            active_stress_policy.profile_name or threshold_profile or settings.abs_stress_threshold_profile,
            sims=resolved_sims,
            seed=resolved_seed,
            pitch_events_csv_path=pitch_events_csv_path,
            artifact_mode=requested_artifact_mode,
        )
        if requested_artifact_mode == ARTIFACT_MODE_FULL_MATRIX:
            _start_background_model_evaluation_refresh(
                active_policy_version=active_stress_policy_version,
                active_threshold_profile=active_stress_policy.profile_name or threshold_profile or settings.abs_stress_threshold_profile,
                pitch_events_csv_path=pitch_events_csv_path,
            )

        row = _get_latest_stress_row_with_timeout(timeout_seconds=2.0)
        if row:
            try:
                return _hydrate_stress_result_from_row(row)
            except Exception as exc:
                print(f"[abs-modal] failed to hydrate persisted stress result in /v1/stress-test/recompute: {exc}")

        if STATE.latest_result is not None:
            return STATE.latest_result

        # First run fallback if there is no cached artifact yet.
        return _run_and_cache_stress_test(
            active_stress_policy,
            active_stress_policy_version,
            active_stress_policy.profile_name or threshold_profile or settings.abs_stress_threshold_profile,
            settings,
            repo,
            sims=min(resolved_sims, 2 if requested_artifact_mode == ARTIFACT_MODE_FULL_MATRIX else 1),
            seed=resolved_seed,
            pitch_events_csv_path=pitch_events_csv_path or settings.abs_production_pitch_events_path,
            artifact_mode=requested_artifact_mode,
            reference_full_row=(
                _get_latest_full_matrix_stress_row_with_timeout(timeout_seconds=2.0)
                if requested_artifact_mode == ARTIFACT_MODE_FAST_BASE
                else None
            ),
        )

    @api.get("/v1/stress-test/latest")
    def stress_test_latest() -> dict[str, Any]:
        # Prefer persisted artifact so UI sees cross-instance updates after recompute.
        row = _get_latest_stress_row_with_timeout(timeout_seconds=3.0)
        if row:
            try:
                hydrated = _hydrate_stress_result_from_row(row)
                if _stress_model_evaluation_incomplete(_coerce_dict(hydrated.get("summary"))):
                    _start_background_model_evaluation_refresh(
                        active_policy_version=settings.abs_stress_policy_version,
                        active_threshold_profile=stress_policy_config.profile_name or settings.abs_stress_threshold_profile,
                        pitch_events_csv_path=settings.pitch_events_csv_path or settings.abs_production_pitch_events_path,
                    )
                return hydrated
            except Exception as exc:
                print(f"[abs-modal] failed to hydrate persisted stress result in /v1/stress-test/latest: {exc}")

        if STATE.latest_result is not None:
            return STATE.latest_result

        # First-run bootstrap keeps Dashboard from showing a hard 404 in Bolt.
        return _run_and_cache_stress_test(
            stress_policy_config,
            settings.abs_stress_policy_version,
            stress_policy_config.profile_name or settings.abs_stress_threshold_profile,
            settings,
            repo,
            sims=1,
            seed=26,
            pitch_events_csv_path=settings.pitch_events_csv_path or settings.abs_production_pitch_events_path,
            artifact_mode=ARTIFACT_MODE_FAST_BASE,
            reference_full_row=_get_latest_full_matrix_stress_row_with_timeout(timeout_seconds=2.0),
        )

    @api.get("/v1/stress-test/status")
    def stress_test_status(
        artifact_mode: str | None = Query(default=None, pattern="^(fast_base|full_matrix)$"),
    ) -> dict[str, Any]:
        latest_row = _get_latest_stress_row_with_timeout(timeout_seconds=2.0)
        latest_generated_at = None
        latest_mode = None
        if isinstance(latest_row, dict):
            latest_generated_at = str(_coerce_dict(latest_row.get("summary")).get("generated_at") or "") or None
            latest_mode = _stress_row_artifact_mode(latest_row)

        if artifact_mode:
            snapshot = _get_recompute_status_snapshot(artifact_mode)
            if latest_generated_at and latest_mode == snapshot.get("artifact_mode") and not snapshot.get("latest_generated_at"):
                snapshot["latest_generated_at"] = latest_generated_at
            return snapshot

        latest_generated_at = latest_generated_at or _stress_result_generated_at(STATE.latest_result)
        modes = [
            _get_recompute_status_snapshot(ARTIFACT_MODE_FAST_BASE),
            _get_recompute_status_snapshot(ARTIFACT_MODE_FULL_MATRIX),
        ]
        if latest_generated_at:
            for mode in modes:
                if not mode.get("latest_generated_at") and latest_mode == mode.get("artifact_mode"):
                    mode["latest_generated_at"] = latest_generated_at
        return {
            "active": any(bool(mode.get("active")) for mode in modes),
            "modes": modes,
        }

    @api.get("/v1/aptitude/top")
    def aptitude_top(limit: int = Query(default=20, ge=1, le=200)) -> list[dict[str, Any]]:
        latest = STATE.latest_result
        if latest is None:
            try:
                latest = stress_test_latest()
            except Exception:
                return []
        if not latest.get("top_aptitudes"):
            latest = _ensure_analysis_artifacts(latest)
        return list(latest.get("top_aptitudes") or [])[:limit]

    @api.get("/v1/memo/latest")
    def memo_latest() -> dict[str, Any]:
        if not STATE.latest_memo:
            if STATE.latest_result is None:
                stress_test_latest()
            _ensure_analysis_artifacts(STATE.latest_result)
            if not STATE.latest_memo and STATE.latest_result is not None:
                decision = STATE.latest_result.get("go_decision", "UNKNOWN")
                STATE.latest_memo = f"# ABS Decision Memo\n\nDecision: **{decision}**"

        if not STATE.latest_memo:
            raise HTTPException(status_code=404, detail="No memo generated")

        latest_ingestion = _get_latest_ingestion_row_with_timeout(timeout_seconds=2.0)
        merged_warnings = list(STATE.latest_memo_assumption_warnings)
        for warning in _memo_outcomes_warnings(latest_ingestion):
            if warning not in merged_warnings:
                merged_warnings.append(warning)

        decision = STATE.latest_result.get("go_decision", "UNKNOWN") if STATE.latest_result else "UNKNOWN"
        return {
            "generated_at": _utc_now_iso(),
            "decision": decision,
            "memo_markdown": STATE.latest_memo,
            "assumption_warnings": merged_warnings,
        }

    @api.get("/v1/ops/metrics")
    def ops_metrics() -> dict[str, object]:
        samples = service.recommend_latency_ms_samples if service is not None else []
        p50 = _percentile(samples, 50)
        p95 = _percentile(samples, 95)
        latest_ingestion = _get_latest_ingestion_row_with_timeout(timeout_seconds=2.0)
        outcomes_metrics = _extract_outcomes_metrics(latest_ingestion)
        latest_ingest_run_at = latest_ingestion.get("run_at") if latest_ingestion else None
        latest_ingest_run_at_str = str(latest_ingest_run_at) if latest_ingest_run_at is not None else None
        fingerprint = latest_ingestion.get("raw_fingerprint") if latest_ingestion else None
        fingerprint_prefix = fingerprint[:8] if isinstance(fingerprint, str) and fingerprint else None
        transformed_row_count = latest_ingestion.get("transformed_row_count") if latest_ingestion else None
        if transformed_row_count is not None:
            try:
                transformed_row_count = int(transformed_row_count)
            except Exception:
                transformed_row_count = None
        ingest_freshness_basis = latest_ingest_run_at_str or STATE.last_ingest_at
        replay_scope_default = _resolve_replay_scope(settings.abs_replay_scope_default)
        replay_rows = None
        replay_games = None
        replay_source_min_date = None
        replay_source_max_date = None
        replay_last_refresh_at = None
        replay_last_refresh_status = None
        replay_backfill_missing_games = None
        replay_backfill_fetched_games = None
        replay_backfill_failed_games = None
        replay_backfill_rows = None
        replay_official_rows_collected = None
        replay_official_rows_linked = None
        replay_official_rows_unmatched = None
        replay_official_rows_used = None
        replay_official_match_rate = None
        core_model_version = settings.abs_core_model_version
        execution_model_version = settings.abs_execution_model_version
        aptitude_model_version = settings.abs_aptitude_model_version
        active_policy_version = settings.abs_stress_policy_version
        overturn_brier_model = None
        overturn_brier_baseline = None
        overturn_brier_improvement = None
        challenged_pitch_auc = None
        calibration_slope = None
        calibration_intercept = None
        brier_by_zone_bucket = None
        reliability_bins = None
        re24_state_drift = None
        pitch_feature_coverage = None
        mismatch_reasons = None
        replay_official_linkage_rate = None
        source_freshness_hours = None
        latest_stress_row = _get_latest_stress_row_with_timeout(timeout_seconds=2.0)
        latest_stress_summary = None
        if isinstance(latest_stress_row, dict):
            latest_stress_summary = _coerce_dict(latest_stress_row.get("summary"))
        elif isinstance(STATE.latest_result, dict):
            latest_stress_summary = _coerce_dict(STATE.latest_result.get("summary"))
        if isinstance(latest_stress_summary, dict):
            policy_version_summary = latest_stress_summary.get("policy_version") or {}
            if isinstance(policy_version_summary, dict):
                core_model_version = policy_version_summary.get("core_model_version") or core_model_version
                execution_model_version = policy_version_summary.get("execution_model_version") or execution_model_version
                aptitude_model_version = policy_version_summary.get("aptitude_model_version") or aptitude_model_version
                active_policy_version = policy_version_summary.get("version_id") or active_policy_version
            model_evaluation = latest_stress_summary.get("model_evaluation") or {}
            if isinstance(model_evaluation, dict):
                overturn_brier_model = model_evaluation.get("brier_model")
                overturn_brier_baseline = model_evaluation.get("brier_baseline")
                overturn_brier_improvement = model_evaluation.get("brier_improvement")
                challenged_pitch_auc = model_evaluation.get("challenged_pitch_auc")
                calibration_slope = model_evaluation.get("calibration_slope")
                calibration_intercept = model_evaluation.get("calibration_intercept")
                brier_by_zone_bucket = model_evaluation.get("brier_by_zone_bucket")
                reliability_bins = model_evaluation.get("reliability_bins")
                re24_state_drift = model_evaluation.get("re24_state_drift")
                pitch_feature_coverage = model_evaluation.get("pitch_feature_coverage")
                mismatch_reasons = model_evaluation.get("mismatch_reasons")
                replay_official_linkage_rate = model_evaluation.get("replay_official_linkage_rate")
                source_freshness_hours = model_evaluation.get("source_freshness_hours")
            if _stress_model_evaluation_incomplete(latest_stress_summary):
                _start_background_model_evaluation_refresh(
                    active_policy_version=str(active_policy_version or settings.abs_stress_policy_version),
                    active_threshold_profile=str(
                        (policy_version_summary.get("threshold_profile") if isinstance(policy_version_summary, dict) else None)
                        or stress_policy_config.profile_name
                        or settings.abs_stress_threshold_profile
                    ),
                    pitch_events_csv_path=settings.pitch_events_csv_path or settings.abs_production_pitch_events_path,
                )
        refresh_meta = _load_replay_refresh_meta(replay_scope_default, _replay_csv_path(replay_scope_default))
        try:
            replay_service = _require_replay_service(replay_scope_default)
            replay_stats = _replay_dataset_stats(replay_scope_default, replay_service)
            replay_rows = replay_stats.get("rows")
            replay_games = replay_stats.get("games")
            replay_source_min_date = replay_stats.get("source_min_game_date")
            replay_source_max_date = replay_stats.get("source_max_game_date")
            replay_last_refresh_at = replay_stats.get("last_refresh_at")
            replay_last_refresh_status = replay_stats.get("last_refresh_status")
        except HTTPException:
            replay_rows = refresh_meta.get("rows")
            replay_games = refresh_meta.get("games")
            replay_source_min_date = refresh_meta.get("source_min_game_date")
            replay_source_max_date = refresh_meta.get("source_max_game_date")
            replay_last_refresh_at = refresh_meta.get("last_refresh_at")
            replay_last_refresh_status = refresh_meta.get("status")
            savant_backfill = refresh_meta.get("savant_statcast_backfill")
            if isinstance(savant_backfill, dict):
                replay_backfill_missing_games = savant_backfill.get("missing_game_count")
                replay_backfill_fetched_games = savant_backfill.get("fetched_game_count")
                replay_backfill_failed_games = savant_backfill.get("failed_game_count")
                replay_backfill_rows = savant_backfill.get("backfill_row_count")
        replay_transform_stats = refresh_meta.get("transform_stats") if isinstance(refresh_meta, dict) else None
        if isinstance(replay_transform_stats, dict):
            replay_official_rows_collected = replay_transform_stats.get("official_outcome_rows_total")
            replay_official_rows_linked = replay_transform_stats.get("actual_challenge_rows_emitted")
            replay_official_rows_unmatched = replay_transform_stats.get("unmatched_rows")
            replay_official_rows_used = replay_transform_stats.get("official_outcome_rows_used")
            replay_official_match_rate = replay_transform_stats.get("official_match_rate")
            mismatch_reasons = mismatch_reasons or replay_transform_stats.get("skip_reasons")
            if replay_official_linkage_rate is None:
                replay_official_linkage_rate = replay_transform_stats.get("official_match_rate")
        details = latest_ingestion.get("details") if isinstance(latest_ingestion, dict) else None
        replay_from_ingestion = details.get("replay_refresh") if isinstance(details, dict) else None
        if isinstance(replay_from_ingestion, dict):
            replay_rows = replay_rows if replay_rows is not None else replay_from_ingestion.get("rows")
            replay_games = replay_games if replay_games is not None else replay_from_ingestion.get("games")
            replay_source_min_date = (
                replay_source_min_date
                if replay_source_min_date is not None
                else replay_from_ingestion.get("source_min_game_date")
            )
            replay_source_max_date = (
                replay_source_max_date
                if replay_source_max_date is not None
                else replay_from_ingestion.get("source_max_game_date")
            )
            replay_last_refresh_at = (
                replay_last_refresh_at
                if replay_last_refresh_at is not None
                else replay_from_ingestion.get("last_refresh_at")
            )
            replay_last_refresh_status = (
                replay_last_refresh_status
                if replay_last_refresh_status is not None
                else replay_from_ingestion.get("status")
            )
            savant_backfill = replay_from_ingestion.get("savant_statcast_backfill")
            if isinstance(savant_backfill, dict):
                replay_backfill_missing_games = (
                    replay_backfill_missing_games
                    if replay_backfill_missing_games is not None
                    else savant_backfill.get("missing_game_count")
                )
                replay_backfill_fetched_games = (
                    replay_backfill_fetched_games
                    if replay_backfill_fetched_games is not None
                    else savant_backfill.get("fetched_game_count")
                )
                replay_backfill_failed_games = (
                    replay_backfill_failed_games
                    if replay_backfill_failed_games is not None
                    else savant_backfill.get("failed_game_count")
                )
                replay_backfill_rows = (
                    replay_backfill_rows
                    if replay_backfill_rows is not None
                    else savant_backfill.get("backfill_row_count")
                )
            replay_transform = replay_from_ingestion.get("transform_stats")
            if isinstance(replay_transform, dict):
                replay_official_rows_collected = (
                    replay_official_rows_collected
                    if replay_official_rows_collected is not None
                    else replay_transform.get("official_outcome_rows_total")
                )
                replay_official_rows_linked = (
                    replay_official_rows_linked
                    if replay_official_rows_linked is not None
                    else replay_transform.get("actual_challenge_rows_emitted")
                )
                replay_official_rows_unmatched = (
                    replay_official_rows_unmatched
                    if replay_official_rows_unmatched is not None
                    else replay_transform.get("unmatched_rows")
                )
                replay_official_rows_used = (
                    replay_official_rows_used
                    if replay_official_rows_used is not None
                    else replay_transform.get("official_outcome_rows_used")
                )
                replay_official_match_rate = (
                    replay_official_match_rate
                    if replay_official_match_rate is not None
                    else replay_transform.get("official_match_rate")
                )
                mismatch_reasons = mismatch_reasons or replay_transform.get("skip_reasons")
                if replay_official_linkage_rate is None:
                    replay_official_linkage_rate = replay_transform.get("official_match_rate")

        if source_freshness_hours is None:
            source_freshness_hours = _source_freshness_hours(
                str(replay_source_max_date) if replay_source_max_date is not None else None
            )

        return {
            "recommend_latency_p50_ms": round(p50, 2) if p50 is not None else None,
            "recommend_latency_p95_ms": round(p95, 2) if p95 is not None else None,
            "core_model_version": core_model_version,
            "policy_version": active_policy_version,
            "execution_model_version": execution_model_version,
            "aptitude_model_version": aptitude_model_version,
            "overturn_brier_model": overturn_brier_model,
            "overturn_brier_baseline": overturn_brier_baseline,
            "overturn_brier_improvement": overturn_brier_improvement,
            "challenged_pitch_auc": challenged_pitch_auc,
            "calibration_slope": calibration_slope,
            "calibration_intercept": calibration_intercept,
            "brier_by_zone_bucket": brier_by_zone_bucket,
            "reliability_bins": reliability_bins,
            "re24_state_drift": re24_state_drift,
            "pitch_feature_coverage": pitch_feature_coverage,
            "mismatch_reasons": mismatch_reasons,
            "replay_official_linkage_rate": replay_official_linkage_rate,
            "source_freshness_hours": source_freshness_hours,
            "ingest_freshness_seconds": _ingest_freshness_seconds(ingest_freshness_basis),
            "last_retrain_at": STATE.last_retrain_at,
            "last_stress_test_at": STATE.last_stress_test_at,
            "data_source_mode": "production" if service is not None else "production-unavailable",
            "last_ingest_status": latest_ingestion.get("status") if latest_ingestion else None,
            "last_ingest_run_at": latest_ingest_run_at_str,
            "last_ingest_row_count": transformed_row_count,
            "last_ingest_fingerprint_prefix": fingerprint_prefix,
            "last_abs_outcomes_status": outcomes_metrics.get("status"),
            "last_abs_outcomes_run_at": outcomes_metrics.get("run_at"),
            "last_abs_outcomes_row_count": outcomes_metrics.get("row_count"),
            "last_abs_outcomes_match_rate": outcomes_metrics.get("match_rate"),
            "last_abs_outcomes_fingerprint_prefix": outcomes_metrics.get("fingerprint_prefix"),
            "last_abs_outcomes_overturn_rate": outcomes_metrics.get("overturn_rate"),
            "last_abs_outcomes_overturned_rows": outcomes_metrics.get("overturned_rows"),
            "last_abs_outcomes_upheld_rows": outcomes_metrics.get("upheld_rows"),
            "last_abs_outcomes_min_challenge_ts": outcomes_metrics.get("min_challenge_ts"),
            "last_abs_outcomes_max_challenge_ts": outcomes_metrics.get("max_challenge_ts"),
            "official_outcomes_rows": outcomes_metrics.get("official_rows"),
            "inferred_outcomes_rows": outcomes_metrics.get("inferred_rows"),
            "official_outcomes_last_refresh_at": outcomes_metrics.get("run_at"),
            "official_outcomes_max_game_date": outcomes_metrics.get("official_max_challenge_ts"),
            "official_outcomes_match_rate": outcomes_metrics.get("official_match_rate"),
            "outcomes_lineage_status": outcomes_metrics.get("outcomes_lineage_status"),
            "savant_benchmark_status": outcomes_metrics.get("savant_benchmark_status"),
            "savant_benchmark_last_refresh_at": outcomes_metrics.get("savant_benchmark_last_refresh_at"),
            "savant_benchmark_years": outcomes_metrics.get("savant_benchmark_years"),
            "savant_benchmark_total_challenges": outcomes_metrics.get("savant_benchmark_total_challenges"),
            "savant_benchmark_total_overturns": outcomes_metrics.get("savant_benchmark_total_overturns"),
            "savant_benchmark_overturn_rate": outcomes_metrics.get("savant_benchmark_overturn_rate"),
            "savant_benchmark_challenge_delta": outcomes_metrics.get("savant_benchmark_challenge_delta"),
            "savant_benchmark_challenge_delta_pct": outcomes_metrics.get("savant_benchmark_challenge_delta_pct"),
            "savant_benchmark_overturn_rate_delta": outcomes_metrics.get("savant_benchmark_overturn_rate_delta"),
            "savant_benchmark_comparison_status": outcomes_metrics.get("savant_benchmark_comparison_status"),
            "official_savant_detail_rows_by_year": outcomes_metrics.get("official_savant_detail_rows_by_year"),
            "official_savant_matched_rows_by_year": outcomes_metrics.get("official_savant_matched_rows_by_year"),
            "official_savant_unmatched_rows_by_year": outcomes_metrics.get("official_savant_unmatched_rows_by_year"),
            "official_savant_unmatched_reason_counts": outcomes_metrics.get("official_savant_unmatched_reason_counts"),
            "official_savant_unmatched_reason_counts_by_year": outcomes_metrics.get(
                "official_savant_unmatched_reason_counts_by_year"
            ),
            "explicit_outcomes_enabled": bool(settings.abs_challenge_outcomes_uri),
            "replay_scope_default": replay_scope_default,
            "replay_rows": replay_rows,
            "replay_games": replay_games,
            "replay_source_min_date": replay_source_min_date,
            "replay_source_max_date": replay_source_max_date,
            "replay_last_refresh_at": replay_last_refresh_at,
            "replay_last_refresh_status": replay_last_refresh_status,
            "replay_backfill_missing_games": replay_backfill_missing_games,
            "replay_backfill_fetched_games": replay_backfill_fetched_games,
            "replay_backfill_failed_games": replay_backfill_failed_games,
            "replay_backfill_rows": replay_backfill_rows,
            "replay_official_rows_collected": replay_official_rows_collected,
            "replay_official_rows_linked": replay_official_rows_linked,
            "replay_official_rows_unmatched": replay_official_rows_unmatched,
            "replay_official_rows_used": replay_official_rows_used,
            "replay_official_match_rate": replay_official_match_rate,
        }

    @api.get("/v1/research/official-outcomes-breakdown")
    def official_outcomes_breakdown(team: str | None = Query(default=None)) -> dict[str, Any]:
        return _official_outcomes_breakdown_payload(team=team)

    @api.get("/v1/research/missed-opportunities")
    def missed_opportunities(
        year: str = Query(default="2026"),
        game_type: str = Query(default="R"),
        team: str | None = Query(default=None),
    ) -> dict[str, Any]:
        statcast_source = settings.abs_pitching_change_source_path
        if not statcast_source:
            raise HTTPException(status_code=503, detail="Statcast source is not configured")
        # If the source is a URI, download to /tmp first
        local_statcast_path = statcast_source
        if statcast_source.startswith("http://") or statcast_source.startswith("https://"):
            local_statcast_path = "/tmp/statcast_source_missed_opp.csv"
            fetch_csv_to_path(statcast_source, local_statcast_path, timeout_seconds=600.0)
        outcomes_uri = settings.abs_official_challenge_outcomes_uri or settings.abs_challenge_outcomes_uri
        challenged_pitch_ids: set[str] = set()
        if outcomes_uri:
            try:
                official_rows = load_official_outcomes_rows(outcomes_uri, timeout=30.0)
                challenged_pitch_ids = {row["pitch_id"] for row in official_rows if row.get("pitch_id")}
            except Exception:
                pass
        return compute_missed_opportunities(
            local_statcast_path,
            challenged_pitch_ids,
            year=year,
            game_type=game_type,
            team=team,
            timeout=600.0,
        )

    @api.get("/v1/research/run-value-by-handedness")
    def run_value_by_handedness(
        team: str | None = Query(default=None),
    ) -> dict[str, Any]:
        statcast_source = settings.abs_pitching_change_source_path
        if not statcast_source:
            raise HTTPException(status_code=503, detail="Statcast source is not configured")
        local_statcast_path = statcast_source
        if statcast_source.startswith("http://") or statcast_source.startswith("https://"):
            local_statcast_path = "/tmp/statcast_source_run_value.csv"
            fetch_csv_to_path(statcast_source, local_statcast_path, timeout_seconds=600.0)
        outcomes_uri = settings.abs_official_challenge_outcomes_uri or settings.abs_challenge_outcomes_uri
        overturned_pitch_ids: set[str] = set()
        team_overturned_pitch_ids: set[str] | None = None
        if outcomes_uri:
            try:
                official_rows = load_official_outcomes_rows(outcomes_uri, timeout=30.0)
                overturned_pitch_ids = {
                    row["pitch_id"]
                    for row in official_rows
                    if row.get("pitch_id") and row.get("challenge_result", "").lower() == "overturned"
                }
                if team:
                    team_upper = team.strip().upper()
                    team_overturned_pitch_ids = {
                        row["pitch_id"]
                        for row in official_rows
                        if row.get("pitch_id")
                        and row.get("challenge_result", "").lower() == "overturned"
                        and normalize_challenge_team(str(row.get("challenge_team", ""))) == team_upper
                    }
            except Exception:
                pass
        return compute_run_value_by_handedness(
            local_statcast_path,
            overturned_pitch_ids,
            team=team,
            team_overturned_pitch_ids=team_overturned_pitch_ids,
            timeout=600.0,
        )

    @api.get("/v1/research/actual-vs-policy-summary")
    def actual_vs_policy_summary(
        scope: str = Query(default="abs_only", pattern="^(abs_only|all)$"),
        team: str | None = Query(default=None),
        year: str | None = Query(default=None),
        game_type: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return _actual_vs_policy_summary_payload(scope, team=team, year=year, game_type=game_type)

    def _parse_pitcher_fatigue_seasons_query(seasons: str) -> tuple[int, ...]:
        try:
            season_values = tuple(sorted({int(token.strip()) for token in seasons.split(",") if token.strip()}))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid seasons query: {seasons}") from exc
        if not season_values:
            raise HTTPException(status_code=400, detail="At least one season must be provided")
        return season_values

    def _build_pitcher_fatigue_research_payload(
        *,
        seasons: str,
        starter_target: int,
        reliever_target: int,
        include_starter_signal_context: bool,
    ) -> tuple[dict[str, Any], tuple[int, ...]]:
        statcast_source = settings.abs_pitching_change_source_path
        if not statcast_source:
            raise HTTPException(status_code=503, detail="Statcast source is not configured")

        local_statcast_path = statcast_source
        if statcast_source.startswith("http://") or statcast_source.startswith("https://"):
            local_statcast_path = "/tmp/pitcher_fatigue_research_source.csv"
            fetch_csv_to_path(statcast_source, local_statcast_path, timeout_seconds=600.0)

        season_values = _parse_pitcher_fatigue_seasons_query(seasons)
        active_rosters_csv_path = (
            settings.abs_pitching_active_rosters_path
            or discover_pitching_active_rosters_csv_path(str(ROOT))
        )
        if not active_rosters_csv_path and settings.abs_pitching_active_rosters_uri:
            active_rosters_csv_path = "/tmp/pitcher_fatigue_active_rosters.csv"
            fetch_csv_to_path(
                settings.abs_pitching_active_rosters_uri,
                active_rosters_csv_path,
                timeout_seconds=60.0,
            )
        bullpen_roles_csv_path = (
            settings.abs_pitching_bullpen_roles_path
            or discover_pitching_bullpen_roles_csv_path(str(ROOT))
        )
        if not bullpen_roles_csv_path and settings.abs_pitching_bullpen_roles_uri:
            bullpen_roles_csv_path = "/tmp/pitcher_fatigue_bullpen_roles.csv"
            fetch_csv_to_path(
                settings.abs_pitching_bullpen_roles_uri,
                bullpen_roles_csv_path,
                timeout_seconds=60.0,
            )
        transaction_csv_path = (
            settings.abs_pitching_transactions_path
            or discover_pitching_transactions_csv_path(str(ROOT))
        )
        if not transaction_csv_path and settings.abs_pitching_transactions_uri:
            transaction_csv_path = "/tmp/pitcher_fatigue_transactions.csv"
            fetch_csv_to_path(
                settings.abs_pitching_transactions_uri,
                transaction_csv_path,
                timeout_seconds=60.0,
            )
        player_status_csv_path = (
            settings.abs_pitching_player_status_path
            or discover_pitching_player_status_csv_path(str(ROOT))
        )
        if not player_status_csv_path and settings.abs_pitching_player_status_uri:
            player_status_csv_path = "/tmp/pitcher_fatigue_player_status.csv"
            fetch_csv_to_path(
                settings.abs_pitching_player_status_uri,
                player_status_csv_path,
                timeout_seconds=60.0,
            )
        payload = build_pitcher_fatigue_research_export(
            local_statcast_path,
            seasons=season_values,
            starter_target=starter_target,
            reliever_target=reliever_target,
            statcast_backfill_csv_path=discover_pitching_backfill_csv_path(str(ROOT)),
            active_rosters_csv_path=active_rosters_csv_path,
            bullpen_roles_csv_path=bullpen_roles_csv_path,
            transaction_csv_path=transaction_csv_path,
            player_status_csv_path=player_status_csv_path,
            include_starter_signal_context=include_starter_signal_context,
        )
        return payload, season_values

    def _build_pitcher_fatigue_research_analysis_response(
        *,
        seasons: str,
        starter_target: int,
        reliever_target: int,
        include_starter_signal_context: bool,
        include_brief: bool,
    ) -> dict[str, Any]:
        payload, season_values = _build_pitcher_fatigue_research_payload(
            seasons=seasons,
            starter_target=starter_target,
            reliever_target=reliever_target,
            include_starter_signal_context=include_starter_signal_context,
        )
        analysis = build_pitcher_fatigue_research_summary(payload)
        analysis = attach_pitcher_hook_context_to_summary(analysis, _latest_pitcher_hook_dataset_summary())
        response = {
            "query": {
                "seasons": list(season_values),
                "starter_target": int(starter_target),
                "reliever_target": int(reliever_target),
                "include_starter_signal_context": bool(include_starter_signal_context),
            },
            "export_summary": dict(payload.get("summary") or {}),
            "analysis": analysis,
        }
        if include_brief:
            response["brief_markdown"] = render_pitcher_fatigue_research_brief(payload, analysis)
        _pitching_store_put(PITCHER_FATIGUE_RESEARCH_LATEST_KEY, response)
        return response

    def _build_pitcher_fatigue_research_presentation_response(
        *,
        seasons: str,
        starter_target: int,
        reliever_target: int,
        include_starter_signal_context: bool,
    ) -> dict[str, Any]:
        payload, season_values = _build_pitcher_fatigue_research_payload(
            seasons=seasons,
            starter_target=starter_target,
            reliever_target=reliever_target,
            include_starter_signal_context=include_starter_signal_context,
        )
        analysis = build_pitcher_fatigue_research_summary(payload)
        analysis = attach_pitcher_hook_context_to_summary(analysis, _latest_pitcher_hook_dataset_summary())
        presentation = build_pitcher_fatigue_sig_presentation(payload, analysis)
        response = {
            "query": {
                "seasons": list(season_values),
                "starter_target": int(starter_target),
                "reliever_target": int(reliever_target),
                "include_starter_signal_context": bool(include_starter_signal_context),
            },
            "export_summary": dict(payload.get("summary") or {}),
            "analysis": analysis,
            "presentation": presentation,
            "memo_markdown": render_pitcher_fatigue_sig_memo(payload, analysis, presentation),
        }
        _pitching_store_put(PITCHER_FATIGUE_RESEARCH_PRESENTATION_LATEST_KEY, response)
        return response

    @api.get("/v1/research/pitcher-fatigue-recovery")
    def pitcher_fatigue_recovery_export(
        seasons: str = Query(default="2024,2025,2026"),
        starter_target: int = Query(default=90, ge=1, le=300),
        reliever_target: int = Query(default=150, ge=1, le=500),
        include_appearances: bool = Query(default=False),
        appearance_limit: int | None = Query(default=None, ge=1, le=50000),
        include_starter_signal_context: bool = Query(default=True),
    ) -> dict[str, Any]:
        payload, _ = _build_pitcher_fatigue_research_payload(
            seasons=seasons,
            starter_target=starter_target,
            reliever_target=reliever_target,
            include_starter_signal_context=include_starter_signal_context,
        )
        if include_appearances:
            appearances = list(payload.get("appearances") or [])
            if appearance_limit is not None:
                appearances = appearances[:appearance_limit]
            payload["appearances"] = appearances
        else:
            payload["appearances"] = []
        payload["summary"]["appearances_in_response"] = len(payload.get("appearances") or [])
        return payload

    @api.get("/v1/research/pitcher-fatigue-recovery/summary")
    def pitcher_fatigue_recovery_summary(
        seasons: str = Query(default="2024,2025,2026"),
        starter_target: int = Query(default=90, ge=1, le=300),
        reliever_target: int = Query(default=150, ge=1, le=500),
        include_starter_signal_context: bool = Query(default=True),
    ) -> dict[str, Any]:
        return _build_pitcher_fatigue_research_analysis_response(
            seasons=seasons,
            starter_target=starter_target,
            reliever_target=reliever_target,
            include_starter_signal_context=include_starter_signal_context,
            include_brief=False,
        )

    @api.get("/v1/research/pitcher-fatigue-recovery/brief")
    def pitcher_fatigue_recovery_brief(
        seasons: str = Query(default="2024,2025,2026"),
        starter_target: int = Query(default=90, ge=1, le=300),
        reliever_target: int = Query(default=150, ge=1, le=500),
        include_starter_signal_context: bool = Query(default=True),
    ) -> dict[str, Any]:
        return _build_pitcher_fatigue_research_analysis_response(
            seasons=seasons,
            starter_target=starter_target,
            reliever_target=reliever_target,
            include_starter_signal_context=include_starter_signal_context,
            include_brief=True,
        )

    @api.get("/v1/research/pitcher-fatigue-recovery/latest")
    def pitcher_fatigue_recovery_latest() -> dict[str, Any]:
        payload = _pitching_store_get(PITCHER_FATIGUE_RESEARCH_LATEST_KEY)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="No pitcher fatigue research summary has been built yet")
        return payload

    @api.get("/v1/research/pitcher-fatigue-recovery/presentation")
    def pitcher_fatigue_recovery_presentation(
        seasons: str = Query(default="2024,2025,2026"),
        starter_target: int = Query(default=90, ge=1, le=300),
        reliever_target: int = Query(default=150, ge=1, le=500),
        include_starter_signal_context: bool = Query(default=True),
    ) -> dict[str, Any]:
        return _build_pitcher_fatigue_research_presentation_response(
            seasons=seasons,
            starter_target=starter_target,
            reliever_target=reliever_target,
            include_starter_signal_context=include_starter_signal_context,
        )

    @api.get("/v1/research/pitcher-fatigue-recovery/presentation/latest")
    def pitcher_fatigue_recovery_presentation_latest() -> dict[str, Any]:
        payload = _pitching_store_get(PITCHER_FATIGUE_RESEARCH_PRESENTATION_LATEST_KEY)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="No pitcher fatigue presentation pack has been built yet")
        return payload

    @api.get("/v1/research/pitcher-fatigue-recovery/presentation/bundle")
    def pitcher_fatigue_recovery_presentation_bundle(
        seasons: str = Query(default=DEFAULT_PITCHER_FATIGUE_RESEARCH_SEASONS),
        starter_target: int = Query(default=90, ge=1, le=300),
        reliever_target: int = Query(default=150, ge=1, le=500),
        include_starter_signal_context: bool = Query(default=True),
        include_charts: bool = Query(default=True),
    ) -> dict[str, Any]:
        try:
            bundle = build_pitcher_fatigue_research_bundle_response(
                settings,
                seasons=seasons,
                starter_target=starter_target,
                reliever_target=reliever_target,
                include_starter_signal_context=include_starter_signal_context,
                include_charts=include_charts,
                hook_dataset_summary=_latest_pitcher_hook_dataset_summary(),
                root=str(ROOT),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        _pitching_store_put(PITCHER_FATIGUE_RESEARCH_BUNDLE_LATEST_KEY, bundle)
        return bundle

    @api.get("/v1/research/pitcher-fatigue-recovery/presentation/bundle/latest")
    def pitcher_fatigue_recovery_presentation_bundle_latest() -> dict[str, Any]:
        payload = _pitching_store_get(PITCHER_FATIGUE_RESEARCH_BUNDLE_LATEST_KEY)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="No pitcher fatigue presentation bundle has been built yet")
        return payload

    @api.post("/v1/research/pitcher-fatigue-recovery/refresh")
    def pitcher_fatigue_recovery_refresh(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        seasons = str(body.get("seasons") or DEFAULT_PITCHER_FATIGUE_RESEARCH_SEASONS)
        starter_target = int(body.get("starter_target") or 90)
        reliever_target = int(body.get("reliever_target") or 150)
        include_starter_signal_context = _coerce_boolish(body.get("include_starter_signal_context", True))
        include_charts = _coerce_boolish(body.get("include_charts", True))
        background = _coerce_boolish(body.get("background", True))
        if background:
            return _build_pitcher_fatigue_refresh_response(
                _start_background_pitcher_fatigue_refresh(
                    seasons=seasons,
                    starter_target=starter_target,
                    reliever_target=reliever_target,
                    include_starter_signal_context=include_starter_signal_context,
                    include_charts=include_charts,
                )
            )
        try:
            return _build_pitcher_fatigue_refresh_response(
                _refresh_and_persist_pitcher_fatigue_research(
                    settings,
                    seasons=seasons,
                    starter_target=starter_target,
                    reliever_target=reliever_target,
                    include_starter_signal_context=include_starter_signal_context,
                    include_charts=include_charts,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @api.get("/v1/research/pitcher-fatigue-recovery/refresh")
    def pitcher_fatigue_recovery_refresh_get(
        seasons: str = Query(default=DEFAULT_PITCHER_FATIGUE_RESEARCH_SEASONS),
        starter_target: int = Query(default=90, ge=1, le=300),
        reliever_target: int = Query(default=150, ge=1, le=500),
        include_starter_signal_context: bool = Query(default=True),
        include_charts: bool = Query(default=True),
        background: bool = Query(default=True),
    ) -> dict[str, Any]:
        if background:
            return _build_pitcher_fatigue_refresh_response(
                _start_background_pitcher_fatigue_refresh(
                    seasons=seasons,
                    starter_target=starter_target,
                    reliever_target=reliever_target,
                    include_starter_signal_context=include_starter_signal_context,
                    include_charts=include_charts,
                )
            )
        try:
            return _build_pitcher_fatigue_refresh_response(
                _refresh_and_persist_pitcher_fatigue_research(
                    settings,
                    seasons=seasons,
                    starter_target=starter_target,
                    reliever_target=reliever_target,
                    include_starter_signal_context=include_starter_signal_context,
                    include_charts=include_charts,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @api.get("/v1/research/pitcher-fatigue-recovery/status")
    def pitcher_fatigue_recovery_status() -> dict[str, Any]:
        return _load_pitcher_fatigue_refresh_status()

    @api.get("/v1/research/pitcher-hook-dataset")
    def pitcher_hook_dataset_export(
        seasons: str = Query(default=DEFAULT_PITCHER_HOOK_DATASET_SEASONS),
        starter_target: int = Query(default=90, ge=1, le=300),
        reliever_target: int = Query(default=150, ge=1, le=500),
        min_pitch_count: int | None = Query(default=None, ge=1, le=250),
        preview_only: bool = Query(default=False),
    ) -> dict[str, Any]:
        try:
            dataset, _ = build_pitcher_hook_dataset_payload(
                settings,
                seasons=seasons,
                starter_target=starter_target,
                reliever_target=reliever_target,
                min_pitch_count=min_pitch_count,
                root=str(ROOT),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if preview_only:
            return build_pitcher_hook_dataset_preview_payload(dataset)
        return dataset

    @api.get("/v1/research/pitcher-hook-dataset/summary")
    def pitcher_hook_dataset_summary(
        seasons: str = Query(default=DEFAULT_PITCHER_HOOK_DATASET_SEASONS),
        starter_target: int = Query(default=90, ge=1, le=300),
        reliever_target: int = Query(default=150, ge=1, le=500),
        min_pitch_count: int | None = Query(default=None, ge=1, le=250),
    ) -> dict[str, Any]:
        try:
            dataset, _ = build_pitcher_hook_dataset_payload(
                settings,
                seasons=seasons,
                starter_target=starter_target,
                reliever_target=reliever_target,
                min_pitch_count=min_pitch_count,
                root=str(ROOT),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return build_pitcher_hook_dataset_preview_payload(dataset)

    @api.post("/v1/research/pitcher-hook-dataset/refresh")
    def pitcher_hook_dataset_refresh(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        seasons = str(body.get("seasons") or DEFAULT_PITCHER_HOOK_DATASET_SEASONS)
        starter_target = int(body.get("starter_target") or 90)
        reliever_target = int(body.get("reliever_target") or 150)
        min_pitch_count = body.get("min_pitch_count")
        background = _coerce_boolish(body.get("background", True))
        if background:
            return _build_pitcher_hook_refresh_response(
                _start_background_pitcher_hook_refresh(
                    seasons=seasons,
                    starter_target=starter_target,
                    reliever_target=reliever_target,
                    min_pitch_count=min_pitch_count,
                )
            )
        try:
            return _build_pitcher_hook_refresh_response(
                _refresh_and_persist_pitcher_hook_dataset(
                    settings,
                    seasons=seasons,
                    starter_target=starter_target,
                    reliever_target=reliever_target,
                    min_pitch_count=min_pitch_count,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @api.get("/v1/research/pitcher-hook-dataset/refresh")
    def pitcher_hook_dataset_refresh_get(
        seasons: str = Query(default=DEFAULT_PITCHER_HOOK_DATASET_SEASONS),
        starter_target: int = Query(default=90, ge=1, le=300),
        reliever_target: int = Query(default=150, ge=1, le=500),
        min_pitch_count: int | None = Query(default=None, ge=1, le=250),
        background: bool = Query(default=True),
    ) -> dict[str, Any]:
        if background:
            return _build_pitcher_hook_refresh_response(
                _start_background_pitcher_hook_refresh(
                    seasons=seasons,
                    starter_target=starter_target,
                    reliever_target=reliever_target,
                    min_pitch_count=min_pitch_count,
                )
            )
        try:
            return _build_pitcher_hook_refresh_response(
                _refresh_and_persist_pitcher_hook_dataset(
                    settings,
                    seasons=seasons,
                    starter_target=starter_target,
                    reliever_target=reliever_target,
                    min_pitch_count=min_pitch_count,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @api.get("/v1/research/pitcher-hook-dataset/status")
    def pitcher_hook_dataset_status() -> dict[str, Any]:
        return _load_pitcher_hook_refresh_status()

    @api.get("/v1/research/pitcher-hook-dataset/latest")
    def pitcher_hook_dataset_latest() -> dict[str, Any]:
        payload = _pitcher_hook_store_get(PITCHER_HOOK_DATASET_LATEST_KEY)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="No pitcher hook dataset has been built yet")
        return payload

    @api.get("/v1/research/pitching-support-inputs")
    def pitching_support_inputs_export(
        seasons: str = Query(default=DEFAULT_PITCHING_SUPPORT_SEASONS),
        game_types: str = Query(default=DEFAULT_PITCHING_SUPPORT_GAME_TYPES),
        timeout_seconds: float = Query(default=20.0, ge=1.0, le=120.0),
        preview_only: bool = Query(default=False),
        upload_outputs: bool = Query(default=False),
    ) -> dict[str, Any]:
        try:
            payload, _, _ = build_pitching_support_inputs_payload(
                settings,
                seasons=seasons,
                game_types=game_types,
                timeout_seconds=timeout_seconds,
                upload_outputs=upload_outputs,
                root=str(ROOT),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if preview_only:
            return build_pitching_support_inputs_preview_payload(payload)
        return payload

    @api.get("/v1/research/pitching-support-inputs/summary")
    def pitching_support_inputs_summary(
        seasons: str = Query(default=DEFAULT_PITCHING_SUPPORT_SEASONS),
        game_types: str = Query(default=DEFAULT_PITCHING_SUPPORT_GAME_TYPES),
        timeout_seconds: float = Query(default=20.0, ge=1.0, le=120.0),
        upload_outputs: bool = Query(default=False),
    ) -> dict[str, Any]:
        try:
            payload, _, _ = build_pitching_support_inputs_payload(
                settings,
                seasons=seasons,
                game_types=game_types,
                timeout_seconds=timeout_seconds,
                upload_outputs=upload_outputs,
                root=str(ROOT),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return build_pitching_support_inputs_preview_payload(payload)

    @api.post("/v1/research/pitching-support-inputs/refresh")
    def pitching_support_inputs_refresh(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        seasons = str(body.get("seasons") or DEFAULT_PITCHING_SUPPORT_SEASONS)
        game_types = str(body.get("game_types") or DEFAULT_PITCHING_SUPPORT_GAME_TYPES)
        timeout_seconds = float(body.get("timeout_seconds") or 20.0)
        upload_outputs = _coerce_boolish(body.get("upload_outputs", True))
        background = _coerce_boolish(body.get("background", True))
        chain_pitcher_hook_dataset = _coerce_boolish(body.get("chain_pitcher_hook_dataset", False))
        if background:
            return _build_pitching_support_refresh_response(
                _start_background_pitching_support_refresh(
                    seasons=seasons,
                    game_types=game_types,
                    timeout_seconds=timeout_seconds,
                    upload_outputs=upload_outputs,
                    chain_pitcher_hook_dataset=chain_pitcher_hook_dataset,
                )
            )
        try:
            support_result = _refresh_and_persist_pitching_support_inputs(
                settings,
                seasons=seasons,
                game_types=game_types,
                timeout_seconds=timeout_seconds,
                upload_outputs=upload_outputs,
                return_payload=chain_pitcher_hook_dataset,
            )
            if chain_pitcher_hook_dataset:
                snapshot, support_payload = support_result
            else:
                snapshot = support_result
                support_payload = None
            if chain_pitcher_hook_dataset:
                support_summary = dict((support_payload or {}).get("summary") or {})
                _refresh_and_persist_pitcher_hook_dataset(
                    settings,
                    seasons=DEFAULT_PITCHER_HOOK_DATASET_SEASONS,
                    starter_target=90,
                    reliever_target=150,
                    min_pitch_count=settings.abs_pitching_min_pitch_count,
                    active_rosters_csv_path_override=str(support_summary.get("active_rosters_csv_path") or ""),
                    bullpen_roles_csv_path_override=str(support_summary.get("bullpen_roles_csv_path") or ""),
                )
            return _build_pitching_support_refresh_response(snapshot)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @api.get("/v1/research/pitching-support-inputs/refresh")
    def pitching_support_inputs_refresh_get(
        seasons: str = Query(default=DEFAULT_PITCHING_SUPPORT_SEASONS),
        game_types: str = Query(default=DEFAULT_PITCHING_SUPPORT_GAME_TYPES),
        timeout_seconds: float = Query(default=20.0, ge=1.0, le=120.0),
        upload_outputs: bool = Query(default=True),
        background: bool = Query(default=True),
        chain_pitcher_hook_dataset: bool = Query(default=False),
    ) -> dict[str, Any]:
        if background:
            return _build_pitching_support_refresh_response(
                _start_background_pitching_support_refresh(
                    seasons=seasons,
                    game_types=game_types,
                    timeout_seconds=timeout_seconds,
                    upload_outputs=upload_outputs,
                    chain_pitcher_hook_dataset=chain_pitcher_hook_dataset,
                )
            )
        try:
            support_result = _refresh_and_persist_pitching_support_inputs(
                settings,
                seasons=seasons,
                game_types=game_types,
                timeout_seconds=timeout_seconds,
                upload_outputs=upload_outputs,
                return_payload=chain_pitcher_hook_dataset,
            )
            if chain_pitcher_hook_dataset:
                snapshot, support_payload = support_result
            else:
                snapshot = support_result
                support_payload = None
            if chain_pitcher_hook_dataset:
                support_summary = dict((support_payload or {}).get("summary") or {})
                _refresh_and_persist_pitcher_hook_dataset(
                    settings,
                    seasons=DEFAULT_PITCHER_HOOK_DATASET_SEASONS,
                    starter_target=90,
                    reliever_target=150,
                    min_pitch_count=settings.abs_pitching_min_pitch_count,
                    active_rosters_csv_path_override=str(support_summary.get("active_rosters_csv_path") or ""),
                    bullpen_roles_csv_path_override=str(support_summary.get("bullpen_roles_csv_path") or ""),
                )
            return _build_pitching_support_refresh_response(snapshot)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @api.get("/v1/research/pitching-support-inputs/status")
    def pitching_support_inputs_status() -> dict[str, Any]:
        return _load_pitching_support_refresh_status()

    @api.get("/v1/research/pitching-support-inputs/latest")
    def pitching_support_inputs_latest() -> dict[str, Any]:
        payload = _pitching_support_store_get(PITCHING_SUPPORT_INPUTS_LATEST_KEY)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="No pitching support inputs have been built yet")
        return payload

    def _seed_replay_startup_state() -> None:
        try:
            replay_scope_default = _resolve_replay_scope(settings.abs_replay_scope_default)
            replay_path = _replay_csv_path(replay_scope_default)
            refresh_meta = _load_replay_refresh_meta(replay_scope_default, replay_path)
            if refresh_meta:
                STATE.replay_refresh_meta[replay_scope_default] = refresh_meta
            _load_ranked_games_catalog(replay_scope_default)
        except Exception as exc:
            print(f"[abs-modal] replay startup seed failed for scope={settings.abs_replay_scope_default}: {exc}")

    # Startup only seeds lightweight persisted replay artifacts. Process-local
    # payload warming stays on the replay refresh path, where it actually warms
    # the worker handling those requests without leaving orphaned startup threads.
    _seed_replay_startup_state()
    _seed_pitching_startup_state()

    return api


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=7200,
    max_containers=1,
)
def replay_refresh_job(
    *,
    scope: str,
    start_date: str | None = None,
    end_date: str | None = None,
    requested_at: str | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    resolved_scope = normalize_replay_scope(scope, settings.abs_replay_scope_default)
    replay_path = replay_output_path(settings, resolved_scope)
    existing_meta = read_replay_refresh_meta(replay_path) or {}
    started_at = _utc_now_iso()
    running_meta = _build_replay_refresh_status_payload(
        settings=settings,
        scope=resolved_scope,
        status="running",
        start_date=start_date,
        end_date=end_date,
        requested_at=requested_at or started_at,
        started_at=started_at,
        existing_meta=existing_meta if isinstance(existing_meta, dict) else None,
    )
    write_replay_refresh_meta(replay_path, running_meta)
    # Persist running status to Modal Dict so API containers (different filesystem)
    # can see the job is in progress and avoid spawning duplicates.
    try:
        replay_catalog_store.put(f"meta:{resolved_scope}", running_meta)
    except Exception as _dict_exc:
        print(f"[abs-modal] replay refresh job failed to persist running meta to Dict: {_dict_exc}")
    print(
        f"[abs-modal] replay refresh job started scope={resolved_scope} "
        f"start_date={start_date or ''} end_date={end_date or ''}"
    )
    try:
        refresh_meta = build_replay_dataset(
            settings=settings,
            scope=resolved_scope,
            start_date=start_date,
            end_date=end_date,
        )
        catalog_status = refresh_meta.get("catalog_status")
        catalog_error = refresh_meta.get("catalog_error")
        if catalog_status != "success":
            print(
                f"[abs-modal] replay refresh job: catalog build status={catalog_status!r}"
                f" error={catalog_error!r}"
            )
        catalog = read_replay_catalog(replay_path)
        print(f"[abs-modal] replay refresh job: catalog len={len(catalog)} status={catalog_status!r}")
        if catalog:
            # Persist the enriched catalog (includes linkage_completeness_flag and all
            # game-level stats) to Modal Dict so the fastapi container can read it.
            try:
                replay_catalog_store.put(f"catalog:{resolved_scope}", catalog)
                print(
                    f"[abs-modal] replay refresh job persisted enriched catalog "
                    f"scope={resolved_scope} games={len(catalog)}"
                )
            except Exception as exc:
                print(f"[abs-modal] replay refresh job failed to persist catalog to Dict: {exc}")
            replay_stats = {
                "rows": refresh_meta.get("replay_rows"),
                "games": refresh_meta.get("replay_games"),
                "last_refresh_at": refresh_meta.get("last_refresh_at"),
                "source_min_game_date": refresh_meta.get("source_min_game_date"),
                "source_max_game_date": refresh_meta.get("source_max_game_date"),
            }
            replay_audit_summary = build_actual_vs_policy_summary(
                catalog=catalog,
                official_summary={},
                replay_dataset_stats=replay_stats,
                scope=resolved_scope,
            )
            _set_replay_audit_summary(resolved_scope, replay_audit_summary)
        refresh_meta["requested_at"] = requested_at or started_at
        refresh_meta["started_at"] = started_at
        write_replay_refresh_meta(replay_path, refresh_meta)
        # Persist meta to Modal Dict so the API container (different container) can
        # see the completed status and unblock future refresh triggers.
        try:
            replay_catalog_store.put(f"meta:{resolved_scope}", refresh_meta)
        except Exception as _meta_exc:
            print(f"[abs-modal] replay refresh job failed to persist meta to Dict: {_meta_exc}")
        # Upload built CSV to Supabase so cold-start containers can download it
        # (~60 MB) instead of rebuilding from the 600 MB master.
        if resolved_scope == "abs_only" and settings.abs_replay_output_uri and Path(replay_path).exists():
            try:
                import os as _os
                from urllib.request import Request as _Req, urlopen as _urlopen
                _upload_url = settings.abs_replay_output_uri.replace(
                    "/storage/v1/object/public/", "/storage/v1/object/"
                )
                _file_size = _os.path.getsize(replay_path)
                print(f"[abs-modal] replay refresh job: uploading {_file_size / 1024 / 1024:.1f} MB to {_upload_url}")
                with open(replay_path, "rb") as _f:
                    _req = _Req(
                        _upload_url,
                        data=_f,
                        method="POST",
                        headers={
                            "Authorization": f"Bearer {settings.supabase_service_role_key}",
                            "apikey": settings.supabase_service_role_key,
                            "Content-Type": "text/csv",
                            "Content-Length": str(_file_size),
                            "x-upsert": "true",
                        },
                    )
                    with _urlopen(_req, timeout=300) as _resp:
                        _resp.read()
                print(f"[abs-modal] replay refresh job: replay CSV uploaded successfully")
            except Exception as _up_exc:
                print(f"[abs-modal] replay refresh job: replay CSV upload failed (non-fatal): {_up_exc}")
        return refresh_meta
    except Exception as exc:
        failed_meta = _build_replay_refresh_status_payload(
            settings=settings,
            scope=resolved_scope,
            status="failed",
            start_date=start_date,
            end_date=end_date,
            requested_at=requested_at or started_at,
            started_at=started_at,
            last_refresh_at=_utc_now_iso(),
            error=str(exc),
            existing_meta=existing_meta if isinstance(existing_meta, dict) else None,
        )
        write_replay_refresh_meta(replay_path, failed_meta)
        try:
            replay_catalog_store.put(f"meta:{resolved_scope}", failed_meta)
        except Exception:
            pass
        print(f"[abs-modal] replay refresh job failed scope={resolved_scope}: {exc}")
        raise


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=3600,
    max_containers=1,
)
def pitching_refresh_job(
    *,
    requested_at: str | None = None,
    league: str = DEFAULT_PITCHING_LEAGUE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    print(
        "[abs-modal] pitching refresh job started "
        f"league={league} source={_pitching_refresh_source_label(league=league)} "
        f"window={start_date or 'default'}..{end_date or start_date or 'default'}"
    )
    return _refresh_pitching_artifacts(
        settings,
        requested_at=requested_at,
        league=league,
        start_date=start_date,
        end_date=end_date,
    )


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=10800,
    max_containers=1,
)
def pitching_calibration_job(
    *,
    requested_at: str | None = None,
    season: int = 2026,
    start_date: str | None = None,
    end_date: str | None = None,
    game_type: str = "R",
    min_pitch_count: int | None = None,
    upload_outputs: bool = True,
) -> dict[str, Any]:
    settings = load_settings()
    print(
        "[abs-modal] pitching calibration job started "
        f"season={season} window={start_date or 'default'}..{end_date or 'default'} "
        f"game_type={game_type} min_pitch_count={min_pitch_count or settings.abs_pitching_min_pitch_count}"
    )
    return _run_pitching_calibration(
        settings,
        requested_at=requested_at,
        season=int(season),
        start_date=start_date,
        end_date=end_date,
        game_type=game_type,
        min_pitch_count=min_pitch_count,
        upload_outputs=upload_outputs,
    )


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=10800,
    max_containers=1,
)
def pitching_preventable_runs_model_job(
    *,
    requested_at: str | None = None,
    season: int = 2026,
    training_start_date: str | None = None,
    training_end_date: str | None = None,
    holdout_start_date: str | None = None,
    holdout_end_date: str | None = None,
    game_type: str = "R",
    min_pitch_count: int | None = None,
    upload_outputs: bool = True,
) -> dict[str, Any]:
    settings = load_settings()
    print(
        "[abs-modal] pitching preventable-runs model job started "
        f"season={season} training={training_start_date or 'default'}..{training_end_date or 'default'} "
        f"holdout={holdout_start_date or 'default'}..{holdout_end_date or 'default'} "
        f"game_type={game_type} min_pitch_count={min_pitch_count or settings.abs_pitching_min_pitch_count}"
    )
    return _run_pitching_preventable_runs_model(
        settings,
        requested_at=requested_at,
        season=int(season),
        training_start_date=training_start_date,
        training_end_date=training_end_date,
        holdout_start_date=holdout_start_date,
        holdout_end_date=holdout_end_date,
        game_type=game_type,
        min_pitch_count=min_pitch_count,
        upload_outputs=upload_outputs,
    )


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=7200,
    max_containers=1,
)
def pitching_support_inputs_refresh_job(
    *,
    requested_at: str | None = None,
    seasons: str = DEFAULT_PITCHING_SUPPORT_SEASONS,
    game_types: str = DEFAULT_PITCHING_SUPPORT_GAME_TYPES,
    timeout_seconds: float = 20.0,
    upload_outputs: bool = True,
    chain_pitcher_hook_dataset: bool = False,
) -> dict[str, Any]:
    settings = load_settings()
    print(
        "[abs-modal] pitching support inputs refresh job started "
        f"seasons={seasons} game_types={game_types}"
    )
    support_result = _refresh_and_persist_pitching_support_inputs(
        settings,
        requested_at=requested_at,
        seasons=seasons,
        game_types=game_types,
        timeout_seconds=timeout_seconds,
        upload_outputs=upload_outputs,
        return_payload=chain_pitcher_hook_dataset,
    )
    if chain_pitcher_hook_dataset:
        support_status, support_payload = support_result
    else:
        support_status = support_result
        support_payload = None
    result: dict[str, Any] = {"pitching_support_inputs_refresh": support_status}
    if chain_pitcher_hook_dataset:
        support_summary = dict((support_payload or {}).get("summary") or {})
        hook_status = _refresh_and_persist_pitcher_hook_dataset(
            settings,
            seasons=DEFAULT_PITCHER_HOOK_DATASET_SEASONS,
            starter_target=90,
            reliever_target=150,
            min_pitch_count=settings.abs_pitching_min_pitch_count,
            active_rosters_csv_path_override=str(support_summary.get("active_rosters_csv_path") or ""),
            bullpen_roles_csv_path_override=str(support_summary.get("bullpen_roles_csv_path") or ""),
        )
        result["pitcher_hook_dataset_refresh"] = hook_status
    return result


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=7200,
    max_containers=1,
)
def pitcher_hook_dataset_refresh_job(
    *,
    requested_at: str | None = None,
    seasons: str = DEFAULT_PITCHER_HOOK_DATASET_SEASONS,
    starter_target: int = 90,
    reliever_target: int = 150,
    min_pitch_count: int | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    print(
        "[abs-modal] pitcher hook dataset refresh job started "
        f"seasons={seasons} starter_target={starter_target} reliever_target={reliever_target}"
    )
    return _refresh_and_persist_pitcher_hook_dataset(
        settings,
        requested_at=requested_at,
        seasons=seasons,
        starter_target=starter_target,
        reliever_target=reliever_target,
        min_pitch_count=min_pitch_count,
    )


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=10800,
    max_containers=1,
)
def pitcher_fatigue_research_refresh_job(
    *,
    requested_at: str | None = None,
    seasons: str = DEFAULT_PITCHER_FATIGUE_RESEARCH_SEASONS,
    starter_target: int = 90,
    reliever_target: int = 150,
    include_starter_signal_context: bool = True,
    include_charts: bool = True,
) -> dict[str, Any]:
    settings = load_settings()
    print(
        "[abs-modal] pitcher fatigue research refresh job started "
        f"seasons={seasons} starter_target={starter_target} reliever_target={reliever_target}"
    )
    return _refresh_and_persist_pitcher_fatigue_research(
        settings,
        requested_at=requested_at,
        seasons=seasons,
        starter_target=starter_target,
        reliever_target=reliever_target,
        include_starter_signal_context=include_starter_signal_context,
        include_charts=include_charts,
    )


# ---------------------------------------------------------------------------
# MLB Stats API Refresh Job — real-time ABS challenge discovery from live feeds.
# Scheduled every 4 hours in jobs.py; also triggerable on-demand via API here.
# ---------------------------------------------------------------------------

def _default_statsapi_refresh_status() -> dict[str, Any]:
    return {
        "status": "idle",
        "active": False,
        "requested_at": None,
        "started_at": None,
        "completed_at": None,
        "new_challenge_rows": None,
        "merged_rows": None,
        "last_error": None,
    }


def _load_statsapi_refresh_status() -> dict[str, Any]:
    try:
        payload = statsapi_refresh_store.get("statsapi_refresh_status")
        if isinstance(payload, dict):
            merged = _default_statsapi_refresh_status()
            merged.update(payload)
            return merged
    except Exception:
        pass
    return _default_statsapi_refresh_status()


def _persist_statsapi_refresh_status(snapshot: dict[str, Any]) -> None:
    try:
        statsapi_refresh_store.put("statsapi_refresh_status", snapshot)
    except Exception:
        pass


def _run_statsapi_refresh(*, requested_at: str | None = None) -> dict[str, Any]:
    from datetime import timedelta, timezone as _tz, datetime as _dt
    started_at = _utc_now_iso()
    settings = load_settings()

    running = _default_statsapi_refresh_status()
    running.update({
        "status": "running",
        "active": True,
        "requested_at": requested_at or started_at,
        "started_at": started_at,
    })
    _persist_statsapi_refresh_status(running)

    try:
        outcomes_uri = settings.abs_official_challenge_outcomes_uri or settings.abs_challenge_outcomes_uri
        if not outcomes_uri:
            raise ValueError("No outcomes URI configured (ABS_OFFICIAL_CHALLENGE_OUTCOMES_URI or ABS_CHALLENGE_OUTCOMES_URI)")
        if not settings.supabase_service_role_key:
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY required to upload merged outcomes")

        end_date = _dt.now(_tz.utc).date()
        days_back = max(1, settings.abs_mlb_days_back)
        start_date = end_date - timedelta(days=days_back - 1)
        game_types = [g.strip() for g in settings.abs_mlb_game_types.split(",") if g.strip()] or ["R"]

        print(f"[abs-modal] statsapi-refresh: collecting PKs {start_date} → {end_date} types={game_types}")
        game_pks = collect_game_pks_from_mlb_schedule(
            sport_id=settings.abs_mlb_sport_id,
            game_types=game_types,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            timeout_seconds=60.0,
        )

        if not game_pks:
            completed = _default_statsapi_refresh_status()
            completed.update({
                "status": "completed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "new_challenge_rows": 0,
                "merged_rows": None,
            })
            _persist_statsapi_refresh_status(completed)
            return completed

        print(f"[abs-modal] statsapi-refresh: fetching {len(game_pks)} game feeds")
        collect_result = collect_abs_challenges_from_statsapi(game_pks, timeout_seconds=60.0, max_workers=8)
        new_rows: list[dict[str, str]] = list(collect_result.get("rows") or [])
        print(f"[abs-modal] statsapi-refresh: found {len(new_rows)} challenge rows")

        # Merge with existing official outcomes CSV
        import csv as _csv
        from pathlib import Path as _Path

        local_existing = "/tmp/abs_statsapi_refresh_existing.csv"
        local_merged = "/tmp/abs_statsapi_refresh_merged.csv"
        existing_rows: list[dict[str, str]] = []

        # Download existing
        try:
            fetch_csv_to_path(outcomes_uri, local_existing, timeout_seconds=120.0)
            with _Path(local_existing).open("r", encoding="utf-8", newline="") as fh:
                reader = _csv.DictReader(fh)
                for row in reader:
                    existing_rows.append({str(k): str(v or "") for k, v in row.items()})
        except Exception:
            pass  # first run or unreachable — start fresh

        # Merge: official source beats inferred; newer beats older on equal priority
        merged_index: dict[str, tuple[int, str, dict[str, str]]] = {}
        def _priority(r: dict[str, str]) -> int:
            t = (r.get("outcome_source_type") or "").lower()
            return 2 if t == "official" else (1 if t == "inferred" else 0)
        for r in existing_rows + new_rows:
            pid = (r.get("pitch_id") or "").strip()
            if not pid:
                continue
            ts = (r.get("challenge_initiated_ts") or "").strip()
            pri = _priority(r)
            cur = merged_index.get(pid)
            if cur is None or pri > cur[0] or (pri == cur[0] and ts >= cur[1]):
                merged_index[pid] = (pri, ts, r)

        from infra.modal.jobs import AUTO_OUTCOMES_HEADERS  # noqa: PLC0415
        merged_rows = sorted(
            (payload for _p, _ts, payload in merged_index.values()),
            key=lambda r: ((r.get("challenge_initiated_ts") or ""), (r.get("pitch_id") or "")),
        )
        _Path(local_merged).parent.mkdir(parents=True, exist_ok=True)
        with _Path(local_merged).open("w", encoding="utf-8", newline="") as fh:
            writer = _csv.DictWriter(fh, fieldnames=AUTO_OUTCOMES_HEADERS)
            writer.writeheader()
            for r in merged_rows:
                writer.writerow({h: r.get(h, "") for h in AUTO_OUTCOMES_HEADERS})

        # Upload
        import os as _os
        upload_url = outcomes_uri.replace("/storage/v1/object/public/", "/storage/v1/object/")
        file_size = _os.path.getsize(local_merged)
        req_up = UrlRequest(
            upload_url,
            data=_Path(local_merged).read_bytes(),
            method="POST",
            headers={
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "apikey": settings.supabase_service_role_key,
                "x-upsert": "true",
                "Content-Type": "text/csv",
                "Content-Length": str(file_size),
            },
        )
        with urlopen(req_up, timeout=120) as resp:
            resp.read()

        fp, row_count = compute_fingerprint_and_row_count(local_merged)
        print(f"[abs-modal] statsapi-refresh: uploaded {row_count} rows fingerprint={fp[:8]}")

        completed = _default_statsapi_refresh_status()
        completed.update({
            "status": "completed",
            "active": False,
            "requested_at": requested_at or started_at,
            "started_at": started_at,
            "completed_at": _utc_now_iso(),
            "new_challenge_rows": len(new_rows),
            "merged_rows": row_count,
            "game_pks_fetched": len(game_pks),
            "game_types": game_types,
            "fingerprint": fp,
            "game_results": collect_result.get("game_results"),
        })
        _persist_statsapi_refresh_status(completed)
        return completed

    except Exception as exc:
        failed = _default_statsapi_refresh_status()
        failed.update({
            "status": "failed",
            "active": False,
            "requested_at": requested_at or started_at,
            "started_at": started_at,
            "completed_at": _utc_now_iso(),
            "last_error": str(exc),
        })
        _persist_statsapi_refresh_status(failed)
        raise


# ---------------------------------------------------------------------------
# Data Sync Job — downloads new Statcast days, appends to Supabase master CSV,
# then spawns a pitching refresh. Triggered on-demand via API (no cron slot).
# ---------------------------------------------------------------------------

def _default_data_sync_status() -> dict[str, Any]:
    return {
        "status": "idle",
        "active": False,
        "requested_at": None,
        "started_at": None,
        "completed_at": None,
        "last_sync_date": "2026-03-24",
        "new_rows": None,
        "last_error": None,
    }


def _load_data_sync_status() -> dict[str, Any]:
    try:
        payload = data_sync_store.get("sync_status")
        if isinstance(payload, dict):
            merged = _default_data_sync_status()
            merged.update(payload)
            return merged
    except Exception:
        pass
    return _default_data_sync_status()


def _persist_data_sync_status(snapshot: dict[str, Any]) -> None:
    try:
        data_sync_store.put("sync_status", snapshot)
    except Exception:
        pass


def _run_data_sync(*, requested_at: str | None = None, force_start_date: str | None = None) -> dict[str, Any]:
    import ast
    import os
    import shutil
    import subprocess
    import time as _time
    from datetime import date as _date, timedelta

    started_at = _utc_now_iso()
    settings = load_settings()
    current = _load_data_sync_status()
    last_sync_date = str(current.get("last_sync_date") or "2026-03-24")
    max_empty_retries = 3
    empty_retry_sleep_seconds = 600

    # Sync up through yesterday (today's Savant data is often incomplete)
    end_obj = _date.today() - timedelta(days=1)
    # force_start_date overrides the stored last_sync_date (used for backfills)
    if force_start_date:
        start_obj = _date.fromisoformat(force_start_date)
        print(f"[abs-modal] data-sync: force_start_date={force_start_date}, overriding stored last_sync_date={last_sync_date}")
    else:
        start_obj = _date.fromisoformat(last_sync_date) + timedelta(days=1)

    running = _default_data_sync_status()
    running.update({
        "status": "running",
        "active": True,
        "requested_at": requested_at or started_at,
        "started_at": started_at,
        "last_sync_date": last_sync_date,
    })
    _persist_data_sync_status(running)

    try:
        if start_obj > end_obj:
            print(f"[abs-modal] data-sync: already current through {last_sync_date}, nothing to download")
            completed = _default_data_sync_status()
            completed.update({
                "status": "completed",
                "active": False,
                "requested_at": requested_at or started_at,
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "last_sync_date": last_sync_date,
                "new_rows": 0,
            })
            _persist_data_sync_status(completed)
            return completed

        # Step 1: Download new days from Baseball Savant. When syncing just
        # yesterday's date, Savant may still lag at the old 08:00 UTC window.
        # Retry a few times instead of incorrectly advancing last_sync_date.
        new_days_path = "/tmp/statcast_new_days.csv"
        new_rows = 0
        retry_attempts = 0
        latest_window_only = start_obj == end_obj
        while True:
            print(
                f"[abs-modal] data-sync: downloading {start_obj} → {end_obj} "
                f"(attempt {retry_attempts + 1}/{max_empty_retries + 1})"
            )
            result = subprocess.run(
                [
                    "python3", "/root/project/scripts/backfill_full_season_pitching_statcast.py",
                    "--season", str(end_obj.year),
                    "--game-type", "R",
                    "--start-date", start_obj.isoformat(),
                    "--end-date", end_obj.isoformat(),
                    "--merged-output", new_days_path,
                    "--backfill-output", "/tmp/statcast_new_days_raw.csv",
                    "--sleep-seconds", "0.3",
                ],
                capture_output=True, text=True, timeout=900,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Backfill script failed: {result.stderr[-2000:]}")

            new_rows = 0
            for line in reversed(result.stdout.strip().split("\n")):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        new_rows = int(ast.literal_eval(line).get("total_rows", 0))
                    except Exception:
                        pass
                    break

            if new_rows > 0:
                break
            if not latest_window_only or retry_attempts >= max_empty_retries:
                break

            retry_attempts += 1
            print(
                f"[abs-modal] data-sync: 0 rows for {end_obj.isoformat()} on attempt {retry_attempts}; "
                f"waiting {empty_retry_sleep_seconds}s before retry"
            )
            _time.sleep(empty_retry_sleep_seconds)

        print(f"[abs-modal] data-sync: downloaded {new_rows} new rows")

        if new_rows > 0:
            # Step 2: Stream master CSV from Supabase and append new rows
            master_uri = settings.abs_raw_statcast_uri
            updated_path = "/tmp/statcast_master_updated.csv"
            print(f"[abs-modal] data-sync: streaming master from Supabase")
            req_dl = UrlRequest(master_uri, method="GET", headers={"User-Agent": "the-brain-abs/1.0"})
            try:
                with urlopen(req_dl, timeout=600) as resp, open(updated_path, "wb") as out_f:
                    shutil.copyfileobj(resp, out_f)
            except Exception as dl_exc:
                print(f"[abs-modal] data-sync: master download error ({type(dl_exc).__name__}): {dl_exc}")
                raise
            dl_size = os.path.getsize(updated_path)
            print(f"[abs-modal] data-sync: downloaded master {dl_size / 1024 / 1024:.1f} MB")

            # Append new rows (skip header line of new_days file)
            with open(updated_path, "ab") as out_f, open(new_days_path, "rb") as new_f:
                new_f.readline()  # skip header
                shutil.copyfileobj(new_f, out_f)

            # Step 3: Upload merged file to Supabase (write back to same URI we downloaded from)
            upload_url = master_uri.replace("/storage/v1/object/public/", "/storage/v1/object/")
            print(f"[abs-modal] data-sync: upload target: {upload_url}")
            file_size = os.path.getsize(updated_path)
            print(f"[abs-modal] data-sync: uploading {file_size / 1024 / 1024:.1f} MB to Supabase")
            with open(updated_path, "rb") as f:
                req_up = UrlRequest(
                    upload_url,
                    data=f,
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {settings.supabase_service_role_key}",
                        "apikey": settings.supabase_service_role_key,
                        "Content-Type": "text/csv",
                        "Content-Length": str(file_size),
                        "x-upsert": "true",
                    },
                )
                try:
                    with urlopen(req_up, timeout=600) as resp:
                        resp_body = resp.read()
                        print(f"[abs-modal] data-sync: upload response {resp.status}: {resp_body[:200]}")
                except Exception as upload_exc:
                    import urllib.error as _ue
                    if isinstance(upload_exc, _ue.HTTPError):
                        err_body = upload_exc.read()[:500].decode("utf-8", errors="replace")
                        print(f"[abs-modal] data-sync: upload HTTP {upload_exc.code} error body: {err_body}")
                    else:
                        print(f"[abs-modal] data-sync: upload error ({type(upload_exc).__name__}): {upload_exc}")
                    raise
            print("[abs-modal] data-sync: Supabase upload complete")

        # Step 4: Spawn downstream refreshes only when we actually advanced the
        # source file. If yesterday still has 0 rows after retries, leave
        # last_sync_date unchanged so the next run retries the same baseball date.
        advanced_sync_date = True
        completed_last_sync_date = end_obj.isoformat()
        if latest_window_only and new_rows == 0:
            advanced_sync_date = False
            completed_last_sync_date = last_sync_date
            print(
                f"[abs-modal] data-sync: upstream still missing rows for {end_obj.isoformat()} "
                f"after {retry_attempts + 1} attempts; preserving last_sync_date={last_sync_date}"
            )
        else:
            pitching_refresh_job.spawn(requested_at=_utc_now_iso())
            replay_refresh_job.spawn(scope="abs_only", requested_at=_utc_now_iso())
            pitching_support_inputs_refresh_job.spawn(
                requested_at=_utc_now_iso(),
                seasons=DEFAULT_PITCHING_SUPPORT_SEASONS,
                game_types=DEFAULT_PITCHING_SUPPORT_GAME_TYPES,
                timeout_seconds=20.0,
                upload_outputs=True,
                chain_pitcher_hook_dataset=True,
            )
            # Also refresh challenge data from StatsAPI so new game challenges are picked up
            existing_statsapi = _load_statsapi_refresh_status()
            if not existing_statsapi.get("active"):
                abs_challenge_statsapi_refresh_job.spawn(requested_at=_utc_now_iso())

        completed = _default_data_sync_status()
        completed.update({
            "status": "completed",
            "active": False,
            "requested_at": requested_at or started_at,
            "started_at": started_at,
            "completed_at": _utc_now_iso(),
            "last_sync_date": completed_last_sync_date,
            "new_rows": new_rows,
            "target_sync_date": end_obj.isoformat(),
            "advanced_sync_date": advanced_sync_date,
            "retry_attempts": retry_attempts,
            "upstream_ready": bool(new_rows > 0 or not latest_window_only),
        })
        _persist_data_sync_status(completed)
        return completed

    except Exception as exc:
        failed = _default_data_sync_status()
        failed.update({
            "status": "failed",
            "active": False,
            "requested_at": requested_at or started_at,
            "started_at": started_at,
            "completed_at": _utc_now_iso(),
            "last_sync_date": last_sync_date,
            "last_error": str(exc),
        })
        _persist_data_sync_status(failed)
        raise


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    schedule=modal.Cron("30 10 * * *"),  # 10:30 UTC ≈ 6:30am ET — later than the old 08:00 UTC source pull
    timeout=3600,
    memory=2048,
    max_containers=1,
)
def data_sync_job(*, requested_at: str | None = None, force_start_date: str | None = None) -> dict[str, Any]:
    return _run_data_sync(requested_at=requested_at, force_start_date=force_start_date)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=600,
    max_containers=1,
)
def abs_challenge_statsapi_refresh_job(*, requested_at: str | None = None) -> dict[str, Any]:
    """On-demand Stats API refresh triggered via the API endpoint."""
    return _run_statsapi_refresh(requested_at=requested_at)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=1800,
    max_containers=1,
)
def model_evaluation_refresh_job(
    *,
    active_policy_version: str,
    active_threshold_profile: str,
    pitch_events_csv_path: str | None = None,
    requested_at: str | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    repo = _build_repo(settings)
    started_at = _utc_now_iso()
    _set_model_evaluation_status(
        status="running",
        requested_at=requested_at or started_at,
        started_at=started_at,
    )
    print(
        "[abs-modal] model-evaluation refresh job started "
        f"policy_version={active_policy_version} threshold_profile={active_threshold_profile}"
    )
    try:
        result = _refresh_and_persist_model_evaluation_artifacts(
            active_policy_version=active_policy_version,
            active_threshold_profile=active_threshold_profile,
            pitch_events_csv_path=pitch_events_csv_path,
            settings=settings,
            repo=repo,
        )
        return {
            "ok": True,
            "status": "completed",
            "completed_at": _utc_now_iso(),
            "brier_improvement": result.get("brier_improvement"),
        }
    except Exception as exc:
        failed_at = _utc_now_iso()
        _set_model_evaluation_status(
            status="failed",
            completed_at=failed_at,
            last_error=str(exc),
        )
        print(f"[abs-modal] model-evaluation refresh job failed: {exc}")
        raise


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=1800,
    max_containers=2,
)
def stress_recompute_job(
    *,
    artifact_mode: str,
    sims: int,
    seed: int,
    pitch_events_csv_path: str | None = None,
    threshold_profile: str | None = None,
    policy_version: str | None = None,
    min_overturn_probability: float | None = None,
    obvious_miss_distance: float | None = None,
    requested_at: str | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    repo = _build_repo(settings)
    base_policy = _load_stress_policy_config(settings)
    active_policy = _policy_config_with_overrides(
        base_policy,
        threshold_profile=threshold_profile,
        min_overturn_probability=min_overturn_probability,
        obvious_miss_distance=obvious_miss_distance,
    )
    active_policy_version = str(policy_version or settings.abs_stress_policy_version)
    mode = _artifact_mode_label(artifact_mode)
    started_at = _utc_now_iso()
    _set_recompute_status(
        mode,
        status="running",
        requested_at=requested_at or started_at,
        started_at=started_at,
    )
    print(
        f"[abs-modal] stress recompute job started mode={mode} sims={sims} seed={seed} "
        f"path={pitch_events_csv_path or settings.pitch_events_csv_path or settings.abs_production_pitch_events_path}"
    )
    try:
        result = _run_and_cache_stress_test(
            active_policy,
            active_policy_version,
            active_policy.profile_name or threshold_profile or settings.abs_stress_threshold_profile,
            settings,
            repo,
            sims=int(sims),
            seed=int(seed),
            pitch_events_csv_path=pitch_events_csv_path,
            artifact_mode=mode,
            reference_full_row=(
                _get_latest_reference_full_matrix_row(repo)
                if mode == ARTIFACT_MODE_FAST_BASE
                else None
            ),
        )
        return {
            "ok": True,
            "artifact_mode": mode,
            "generated_at": _stress_result_generated_at(result),
        }
    except Exception as exc:
        failed_at = _utc_now_iso()
        _set_recompute_status(
            mode,
            status="failed",
            completed_at=failed_at,
            last_error=str(exc),
        )
        print(f"[abs-modal] stress recompute job failed mode={mode}: {exc}")
        raise


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("abs-prod")],
    timeout=900,
    min_containers=1,
)
@modal.asgi_app()
def fastapi_app_tuned() -> FastAPI:
    return build_fastapi_app()
