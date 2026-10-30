"""Daily recommendations with explicit data coverage and causal recovery memory.

No stored state: replaying the same observations produces the same result across
refreshes, restarts and chart ranges. Monitoring gaps never erase training data.
"""
from datetime import date, timedelta
import math

MODEL_VERSION = 'recovery-confirmation-v1'
MIN_CHECKINS = 3
RESET_GAP_DAYS = 7
MIN_WORKOUT_DATES = 3
MIN_WORKOUT_SPAN_DAYS = 28
RECOVERY_ALPHA = .35
UPGRADE_BUFFER = .5
UPGRADE_CONFIRMATIONS = 2
RATING_FIELDS = ('tiredness', 'perceived_recovery', 'sore_quad_dom',
                 'sore_posterior', 'sore_upper_push', 'sore_upper_pull')
BOUNDARIES = (6.0, 8.0, 13.0, 14.0)
STATES = ('large_increase', 'increase', 'continue', 'decrease', 'large_decrease')
LABELS = ('Large Increase', 'Increase', 'Continue', 'Decrease', 'Large Decrease')
DETAILS = ('Low fatigue - push hard and increase training load',
           'Below baseline - good time to add volume or intensity',
           'Training load well managed - maintain current approach',
           'Fatigue elevated - reduce volume or intensity today',
           'High fatigue - rest or very light activity only')
FALLBACK_LABEL = 'Continue Training as Normal'


def score_band(score):
    return next((i for i, boundary in enumerate(BOUNDARIES) if score <= boundary), 4)


def subjective_score(entry):
    if entry is None or any(entry.get(k) is None for k in RATING_FIELDS):
        return None
    values = [entry[k] for k in RATING_FIELDS]
    if any(not math.isfinite(v) or not 0 <= v <= 4 for v in values):
        return None
    fatigue = round(.45 * values[0] / 4 + .30 * values[1] / 4
                    + .25 * sum(values[2:]) / 16, 3)
    return round(fatigue * 20, 2)


def objective_load(day, volumes):
    """Seven completed days vs 180 completed days; target-day work is excluded."""
    baseline = {d: v for d, v in volumes.items()
                if day - timedelta(days=180) <= d < day and v > 0}
    recent = sum(v for d, v in baseline.items() if d >= day - timedelta(days=7))
    weekly = sum(baseline.values()) / 26
    score = round(min(20., recent / weekly * 10), 2) if weekly > 0 else None
    sufficient = (len(baseline) >= MIN_WORKOUT_DATES and
                  min(baseline, default=day) <= day - timedelta(days=MIN_WORKOUT_SPAN_DAYS))
    return dict(objective_score=score, workout_data_sufficient=sufficient,
                workout_dates=len(baseline), seven_day_volume=recent,
                baseline_weekly_volume=weekly)


class RecommendationState:
    def __init__(self):
        self.memory = self.state = self.last_observed = None
        self.confirmations = self.consecutive = 0
        self.established = False

    def update(self, day, raw):
        if raw is None:
            self.confirmations = self.consecutive = 0
            return dict(smoothed_score=None, recommendation='insufficient_data',
                        consecutive_checkins=0, monitoring_ready=False)
        gap = (day - self.last_observed).days if self.last_observed else None
        if gap is not None and gap <= 0:
            raise ValueError('Recommendation observations must be chronological')
        if gap is None or gap > RESET_GAP_DAYS:
            self.memory, self.state = raw, score_band(raw)
            self.confirmations = 0
            self.consecutive = 1
            self.established = False
        else:
            self.consecutive = self.consecutive + 1 if gap == 1 else 1
            self.memory = max(raw, RECOVERY_ALPHA * raw + (1 - RECOVERY_ALPHA) * self.memory)
            target = score_band(self.memory)
            if target >= self.state:
                self.state = target
                self.confirmations = 0
            else:
                qualifies = self.memory <= BOUNDARIES[self.state - 1] - UPGRADE_BUFFER
                self.confirmations = (self.confirmations + 1 if gap == 1 else 1) if qualifies else 0
                if self.confirmations >= UPGRADE_CONFIRMATIONS:
                    self.state -= 1
                    self.confirmations = 0
        self.last_observed = day
        self.established = self.established or self.consecutive >= MIN_CHECKINS
        return dict(smoothed_score=round(self.memory, 2),
                    recommendation=STATES[self.state] if self.established else 'insufficient_data',
                    consecutive_checkins=self.consecutive, monitoring_ready=self.established)


def build_history(checkins, volumes, end):
    """Use all prior observations for state; callers slice only after replay."""
    indexed = {date.fromisoformat(r['date']) if isinstance(r['date'], str) else r['date']: r
               for r in checkins}
    eligible = [d for d in indexed if d <= end]
    current = min(eligible) if eligible else end
    state = RecommendationState()
    result = []
    while current <= end:
        sub = subjective_score(indexed.get(current))
        load = objective_load(current, volumes)
        raw = round(.8 * sub + .2 * load['objective_score'], 2) if sub is not None and load['objective_score'] is not None else None
        active = state.update(current, raw if load['workout_data_sufficient'] else None)
        reasons = []
        if sub is None:
            reasons.append('Complete today\'s tiredness, fatigue and four soreness ratings.')
        if not load['workout_data_sufficient']:
            reasons.append('At least three training dates spanning 28 days are needed for the workout baseline.')
        if sub is not None and load['workout_data_sufficient'] and not active['monitoring_ready']:
            reasons.append(f'Collecting consecutive complete check-ins ({active["consecutive_checkins"]}/{MIN_CHECKINS}).')
        key = active['recommendation']
        supported = key != 'insufficient_data'
        label = LABELS[STATES.index(key)] if supported else FALLBACK_LABEL
        detail = DETAILS[STATES.index(key)] if supported else 'Insufficient data to recommend a change. ' + ' '.join(reasons)
        result.append(dict(date=current.isoformat(), model_version=MODEL_VERSION,
                           subjective_score=sub, combined_score=raw, **load, **active,
                           data_sufficient=supported, insufficient_data_reasons=reasons,
                           recommendation_label=label, recommendation_detail=detail))
        current += timedelta(days=1)
    return result
