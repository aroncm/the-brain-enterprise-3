export type TrajectoryLabel =
  | "Rapid decay"
  | "Gradual fade"
  | "Stable"
  | "Settling/recovering"
  | "Volatile";

export type Recommendation =
  | "Hold starter"
  | "Prepare bullpen"
  | "Change pitcher"
  | "Planned tandem"
  | "Monitor only";

export type PitcherDecision = {
  id: string;
  team: string;
  pitcher: string;
  role: "Starter" | "Reliever" | string;
  opponent: string;
  inning: string;
  batterPocket: string;
  trajectoryLabel: TrajectoryLabel | "Pending";
  trajectoryIndex: number | null;
  trajectoryConfidence: number | null;
  decayVelocity: number | null;
  decayAcceleration: number | null;
  recoveryIndex: number | null;
  cliffProbability: number | null;
  currentDegradation: number | null;
  leverageIndex: number | null;
  decisionDelta: number | null;
  estimatedWinProbabilityDelta: number | null;
  starterValueNextWindow: number | null;
  alternativeValueNextWindow: number | null;
  starterRunsNextWindow: number | null;
  alternativeRunsNextWindow: number | null;
  transitionCost: number | null;
  bullpenUsageCost: number | null;
  projectedRunsSaved: number | null;
  modelImpliedRunsSaved?: number | null;
  dollarsProtected: number | null;
  recommendation: Recommendation;
  recommendationReason: string;
  stuffCurve: number[];
  topReasons: string[];
  calibrationStatus: string;
  calibrationBucket?: string | null;
  calibrationSampleCount?: number | null;
  calibrationFactor?: number | null;
  calibrationSource?: string | null;
};

export type BullpenOption = {
  id: string;
  name: string;
  role: string;
  availability: string;
  rss: number | null;
  matchupFit: number | null;
  usageCost: number | null;
  projectedRunsAllowed: number | null;
  netOptionScore: number | null;
};

export type AuditRow = {
  id: string;
  game: string;
  decision: string;
  timing: "Early" | "On time" | "Late" | "Held";
  pitcher?: string | null;
  team?: string | null;
  opponent?: string | null;
  inning?: string | null;
  leverageIndex?: number | null;
  actualDecision?: string | null;
  recommendedDecision?: string | null;
  bestAlternative?: string | null;
  opportunityDescription?: string | null;
  counterfactualSummary?: string | null;
  starterValueNextWindow?: number | null;
  alternativeValueNextWindow?: number | null;
  starterRunsNextWindow?: number | null;
  alternativeRunsNextWindow?: number | null;
  projectedRunsSaved: number | null;
  modelImpliedRunsSaved?: number | null;
  estimatedWinProbabilityDelta: number | null;
  realizedDelayTax: number | null;
  actualRunsAfter: number | null;
  calibrationSampleCount?: number | null;
  calibrationFactor?: number | null;
  note: string;
};

export type TripleAConversionCandidate = {
  id: string;
  affiliate: string;
  parentClub: string;
  pitcher: string;
  currentRole: "Starter" | "Reliever";
  recommendedRole: "2-inning weapon" | "Bulk bridge" | "Pocket specialist" | "Watchlist" | "Mirage risk";
  shortWindowStuffPlus: number;
  secondWindowDecay: number;
  reliefConversionScore: number;
  projectedRunsSaved: number;
  confidence: number;
  mirageRisk: number;
  trackedPitches: number;
  note: string;
};

export type RunSavingSummary = {
  generatedAt: string | null;
  league: "mlb" | "triple_a";
  dataMode: string;
  calibrationStatus: string;
  decisionCount: number;
  bullpenOptionCount: number;
  auditCount: number;
  tripleAConversionCandidateCount: number;
  sourceSnapshotCount: number | null;
  sourceGameCount: number | null;
  calibrationWindowCount?: number | null;
  calibrationBucketCount?: number | null;
};

export type RunSavingBoardPayload = {
  summary: RunSavingSummary;
  decisions: PitcherDecision[];
  bullpenOptions: BullpenOption[];
  audits: AuditRow[];
  tripleAConversionCandidates: TripleAConversionCandidate[];
  calibration?: {
    source: string;
    generatedAt: string | null;
    windowCount: number;
    bucketCount: number;
  };
};

export type PreventableRunsFeatureContribution = {
  feature: string;
  value: number | null;
  weight: number | null;
  contribution: number | null;
};

export type PreventableRunsOpportunityRow = {
  raw?: Record<string, unknown>;
  gameId: string;
  gameDate: string | null;
  team: string;
  opponent: string;
  pitcherId: string | null;
  pitcherName: string;
  pitchId?: string | null;
  inning: number | null;
  half: string | null;
  outs: number | null;
  baseState: string | null;
  pitchCount: number | null;
  currentHomeScore?: number | null;
  currentAwayScore?: number | null;
  finalHomeScore?: number | null;
  finalAwayScore?: number | null;
  status: string | null;
  damageRunsNext6Outs: number | null;
  projectedDamageProbability: number | null;
  projectedRunsThroughNextPocket?: number | null;
  projectedPreventableRuns: number | null;
  actualRunsThroughNextPocket?: number | null;
  actualPreventableRunsProxy?: number | null;
  actualChangeWithinNextPocket?: boolean | null;
  actualChangeInning?: string | null;
  actualChangePitchCount?: number | null;
  actualReplacementPitcher?: string | null;
  actualReplacementPitcherId?: string | null;
  actualReplacementFirstPitchCount?: number | null;
  actualChangeAfterPitches?: number | null;
  actualChangeAfterBatters?: number | null;
  runsAfterModelWindow?: number | null;
  runsAfterModelWindowSource?: string | null;
  damageFlag?: number | null;
  missedHookDamageFlag?: number | null;
  productionDegradation?: number | null;
  normalizedDegradation?: number | null;
  recommendedRelieverId?: string | null;
  recommendedRelieverName?: string | null;
  starterValueNextWindow?: number | null;
  bestRelieverValueNextWindow?: number | null;
  decisionDelta?: number | null;
  allocationBucket?: string | null;
  peakWindow?: boolean | null;
  windowCount?: number | null;
  calibratedPreventableSignal?: number | null;
  calibrationBucket: string | null;
  calibrationSampleCount: number | null;
  calibrationMeanDamage: number | null;
  calibrationConfidence: number | null;
  leverageIndex: number | null;
  degradationScore: number | null;
  decayVelocity: number | null;
  decayAcceleration: number | null;
  topFeatures: PreventableRunsFeatureContribution[];
};

export type PreventableRunsTeamSummary = {
  team: string;
  windowCount: number;
  totalProjectedPreventableRuns: number;
  avgProjectedPreventableRuns: number;
  avgProjectedDamageProbability: number;
  actualPreventableRunsProxy: number | null;
  damageRate: number | null;
  missedHookDamageCount: number;
};

export type PreventableRunsPitcherSummary = {
  team: string;
  pitcherId: string | null;
  pitcherName: string;
  windowCount: number;
  totalProjectedPreventableRuns: number;
  avgProjectedPreventableRuns: number;
  avgProjectedDamageProbability: number;
  actualPreventableRunsProxy: number | null;
  damageRate: number | null;
};

export type PreventableRunsOpportunitiesPayload = {
  status: "available" | "unavailable" | string;
  generatedAt: string | null;
  season: number | null;
  team: string | null;
  rowCount: number;
  sourceRows: number | null;
  source: string | null;
  summary: PreventableRunsTeamSummary | null;
  teamSummaries: PreventableRunsTeamSummary[];
  pitcherSummaries: PreventableRunsPitcherSummary[];
  rows: PreventableRunsOpportunityRow[];
};

export type EnterpriseGameSummary = {
  game_id: string;
  date: string;
  home_team: string;
  away_team: string;
  matchup?: string;
  snapshots?: number;
  stay_count?: number;
  watch_count?: number;
  prep_count?: number;
  pull_now_count?: number;
  generated_at?: string | null;
};

export type EnterpriseGamesPayload = {
  summary: {
    generatedAt: string | null;
    league: "mlb" | "triple_a";
    team?: string | null;
    gameCount: number;
    sourceGameCount?: number | null;
  };
  games: EnterpriseGameSummary[];
};

export type PitcherGameLog = {
  gameId: string;
  date: string;
  matchup: string;
  opponent: string;
  innings: number[];
  pitchWindows: number;
  maxPitchCount: number;
  peakStatus: string;
  maxDegradation: number | null;
  avgDegradation: number | null;
  stuffCurve: number[];
  projectedRunsSaved: number | null;
};

export type PitcherProfile = {
  pitcherId?: string | null;
  pitcher: string;
  team: string;
  appearances: number;
  pitchWindows: number;
  maxDegradation: number | null;
  avgDegradation: number | null;
  pullNowGames: number;
  prepOrWatchGames: number;
  projectedRunsSaved: number | null;
  gameLog: PitcherGameLog[];
};

export type PitcherProfilesPayload = {
  summary: {
    generatedAt: string | null;
    league: "mlb" | "triple_a";
    team?: string | null;
    year?: string | null;
    profileCount: number;
    gameCount: number;
    calibrationWindowCount?: number | null;
  };
  profiles: PitcherProfile[];
};

export type PitchingReplayState = {
  pitch_count_in_game: number;
  official_pitch_count_in_game?: number | null;
  replay_pitch_count_in_game?: number | null;
  times_through_order: number;
  base_state: string;
  leverage_index: number;
  velo_mean_5: number;
  seasonal_velo_baseline: number;
  spin_mean_5?: number | null;
  spin_mean_10?: number | null;
  spin_mean_15?: number | null;
  spin_slope_5?: number | null;
  seasonal_spin_baseline?: number | null;
  velo_mean_10?: number | null;
  velo_mean_15?: number | null;
  velo_slope_5?: number | null;
  location_dispersion_10: number;
  location_dispersion_5?: number | null;
  zone_miss_distance_10: number;
  zone_miss_distance_5?: number | null;
  hard_contact_rate_15: number;
  whiff_rate_15?: number | null;
  ball_rate_10?: number | null;
  strike_rate_10?: number | null;
  strike_rate_stability?: number | null;
  called_strike_rate_15?: number | null;
  chase_proxy_rate_15?: number | null;
  opponent_adjusted_whiff_drop?: number | null;
  opponent_whiff_factor?: number | null;
  pitch_mix_drift_10?: number | null;
  pitch_type_velocity_trends?: Record<string, Record<string, number | string | null | undefined>>;
  pitch_type_spin_trends?: Record<string, Record<string, number | string | null | undefined>>;
  degradation_score: number;
  normalized_degradation_score?: number | null;
  enhanced_degradation_score?: number | null;
  empirical_degradation_percentile?: number | null;
  pitcher_empirical_degradation_percentile?: number | null;
  empirical_degradation_sample_count?: number | null;
  pitcher_empirical_degradation_sample_count?: number | null;
  inning_decay_factor?: number | null;
  tto_decay_factor?: number | null;
  batters_faced_in_game?: number | null;
  official_batters_faced_in_game?: number | null;
  component_contributions?: Record<string, number>;
  normalized_component_scores?: Record<string, number>;
  normalized_weighted_components?: Record<string, number>;
  sourceStatus?: string | null;
  rss_stuff?: number | null;
  rss_command?: number | null;
  rss_outcome?: number | null;
  rss_handoff_risk?: number | null;
  rss_usage_fatigue?: number | null;
  rss_score?: number | null;
  rss_status?: string | null;
  // Step 2 — per-pitcher season-to-date norms for diagnostic factor card
  // "career" ticks. Null until the pitcher has 100+ pitches season-to-date.
  pitcher_norm_whiff_rate?: number | null;
  pitcher_norm_strike_rate?: number | null;
  pitcher_norm_called_strike_rate?: number | null;
  pitcher_norm_chase_proxy_rate?: number | null;
  pitcher_norm_hard_contact_rate?: number | null;
  pitcher_norm_zone_miss_distance?: number | null;
  pitcher_norm_location_dispersion?: number | null;
  pitcher_norm_sample_pitches?: number | null;
};

export type PitchingRelieverCandidate = {
  player_id: string;
  player_name: string;
  bullpen_role?: string | null;
  available: boolean;
  net_option_score: number;
  direct_matchup_fit?: number | null;
  usage_cost?: number | null;
  candidate_source?: string | null;
  exclusion_reason?: string | null;
};

export type PitchingReplayEntry = {
  entry_type?: string;
  snapshot: {
    pitch_id: string;
    pitcher_id: string;
    pitcher_name: string;
    batting_team: string;
    fielding_team: string;
    inning: number;
    half: "top" | "bottom" | string;
    outs: number;
    base_state: string;
    score_diff: number;
    home_score?: number | null;
    away_score?: number | null;
    leverage_index: number;
    px?: number | null;
    pz?: number | null;
    pitch_type?: string | null;
    pitch_name?: string | null;
    release_speed?: number | null;
    pfx_x?: number | null;
    pfx_z?: number | null;
    movement_horizontal_inches?: number | null;
    movement_vertical_inches?: number | null;
    events?: string | null;
    description?: string | null;
    des?: string | null;
    hit_location?: string | null;
    official_scoring_label?: string | null;
    official_event?: string | null;
    official_description?: string | null;
    pitch_call?: string | null;
    hit_classification?: string | null;
    batter_handedness?: string | null;
    batter_id?: string | null;
    batter_name?: string | null;
    balls?: number | null;
    strikes?: number | null;
    role?: string | null;
    team_appearance_order?: number | null;
    current_opponent_runs?: number | null;
    upcoming_hitter_pocket?: {
      hitters?: Array<{
        player_id?: string | null;
        batter_id?: string | null;
        player_name?: string | null;
        batter_name?: string | null;
        name?: string | null;
        stand?: string | null;
        handedness?: string | null;
        batting_order_slot?: number | null;
        threat_score?: number | null;
        split_threat_score?: number | null;
      }>;
      n_left?: number | null;
      n_right?: number | null;
      average_hitter_threat?: number | null;
      max_hitter_threat?: number | null;
      handedness_pattern?: string | null;
    } | null;
    reliever_candidates?: PitchingRelieverCandidate[];
    reliever_state?: PitchingReplayState & {
      rss_stuff?: number | null;
      rss_command?: number | null;
      rss_outcome?: number | null;
      rss_handoff_risk?: number | null;
      rss_usage_fatigue?: number | null;
      rss_score?: number | null;
      rss_status?: string | null;
    };
    starter_state: PitchingReplayState;
  };
  recommendation: {
    status: string;
    confidence: number;
    recommended_reliever_id?: string | null;
    recommended_reliever_name?: string | null;
    starter_value_next_3_hitters?: number;
    best_reliever_value_next_3_hitters?: number;
    decision_delta?: number;
    decision_pressure_score?: number | null;
    decision_pressure_thresholds?: {
      watch?: number | null;
      prep?: number | null;
      pullNow?: number | null;
      pull_now?: number | null;
    } | null;
    estimated_win_probability_delta?: number;
    starter_risk_level?: string;
    independent_degradation_score?: number | null;
    independent_degradation_level?: string | null;
    leveraged_degradation_score?: number | null;
    leveraged_degradation_level?: string | null;
    trigger_driver_type?: string | null;
    gm_summary?: string | null;
    decision_summary?: string | null;
    top_reason_codes: string[];
  };
  top_candidates?: PitchingRelieverCandidate[];
};

export type PitchingReplayResponse = {
  game: {
    game_id: string;
    date: string;
    home_team: string;
    away_team: string;
  };
  summary: {
    snapshots: number;
    stay_count: number;
    watch_count: number;
    prep_count: number;
    pull_now_count: number;
    actual_changes_within_next_pocket: number;
  };
  entries: PitchingReplayEntry[];
  reliever_entries?: PitchingReplayEntry[];
  reliever_summary?: Array<Record<string, unknown>>;
  // A team's starter pulled before the decision-snapshot threshold (e.g. yanked
  // in the 1st). He has no entries, so the UI renders a display-only placeholder
  // card in the appearance switcher.
  early_pull_starters?: EarlyPullStarter[];
};

export type EarlyPullStarter = {
  pitcher_id: string;
  pitcher_name: string;
  fielding_team: string;
  pitch_count: number;
};

export type PitchingAuditWindow = Record<string, unknown> & {
  game_id?: string | number | null;
  game_pk?: string | number | null;
  game_date?: string | null;
  matchup?: string | null;
  team?: string | null;
  pitcher_name?: string | null;
  pitcher?: string | null;
  inning?: number | string | null;
  half?: string | null;
  status?: string | null;
  leverage_index?: number | null;
  projected_runs_saved?: number | null;
  estimated_runs_saved?: number | null;
  estimated_win_probability_delta?: number | null;
  actual_outcome?: string | null;
  note?: string | null;
  counterfactual_summary?: string | null;
  opportunity_description?: string | null;
  starter?: Record<string, unknown> | null;
  top_candidate?: Record<string, unknown> | null;
  recommendation?: Record<string, unknown> | null;
};

export type PitchingAuditSummaryPayload = {
  source_summary?: {
    generated_at?: string | null;
    active_filters?: Record<string, unknown>;
  };
  window_summary?: Record<string, unknown>;
  window_filtered_counts?: Record<string, number>;
  delayed_change_windows?: PitchingAuditWindow[];
  missed_hook_windows?: PitchingAuditWindow[];
  justified_stay_windows?: PitchingAuditWindow[];
  high_leverage_holdouts?: PitchingAuditWindow[];
};

export type PitchingRecapPitcher = {
  pitcher_id: string;
  pitcher_name: string;
  team: string;
  role?: "Starter" | "Reliever" | string;
  pitch_count: number;
  innings_pitched: number;
  runs_allowed_total: number;
  earned_runs_total?: number | null;
  hits_allowed?: number | null;
  walks?: number | null;
  strikeouts?: number | null;
  home_runs?: number | null;
  boxscore?: {
    ip?: string | number | null;
    h?: number | null;
    r?: number | null;
    er?: number | null;
    bb?: number | null;
    so?: number | null;
    hr?: number | null;
    np?: number | null;
  } | null;
  rss_score?: number | null;
  rss_label?: string | null;
  rss_has_measurement?: boolean | null;
  bullpen_signal?: Record<string, unknown> | null;
  first_alert_status?: string | null;
  first_alert_inning?: number | null;
  first_alert_pitch_count?: number | null;
  first_pull_now_inning: number | null;
  first_pull_now_pitch_count: number | null;
  runs_allowed_after_first_alert?: number | null;
  runs_allowed_after_signal: number | null;
  actual_exit_inning?: number | null;
  actual_exit_pitch_count?: number | null;
  missed_hook: boolean;
  peak_status: string;
  status_timeline: { inning: number; peak_status: string }[];
};

export type PitchingGameRecap = {
  game_id?: string | null;
  date?: string | null;
  home_team: string;
  away_team: string;
  final_home_score?: number | null;
  final_away_score?: number | null;
  starters: PitchingRecapPitcher[];
  score_timeline: Array<{
    inning: number;
    half: string;
    runs_scored_against_pitcher: number;
  }>;
};

export type PitchingRecapSettings = {
  league?: "mlb" | "triple_a";
  recap_teams: string[];
  auto_email_teams?: string[];
  finalized_email_teams?: string[];
  enabled_teams?: string[];
  team_recipients: Record<string, string[]>;
  email_provider?: string;
  shared_email_configured?: boolean;
};

export type PitchingRecapEmailResponse = {
  league: "mlb" | "triple_a";
  team: string;
  game_id: string;
  subject?: string;
  recap: PitchingGameRecap;
  html?: string;
  text?: string;
  sent?: boolean;
  sent_to?: string[];
  failed_recipients?: string[];
  recipients?: string[];
};
