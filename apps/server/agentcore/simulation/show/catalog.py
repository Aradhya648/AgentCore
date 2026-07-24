"""节目期目录 — 发布态门禁位 + 竞猜结算（进程内 / 文件仓）。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from agentcore.simulation.show.manifest import EpisodeManifest
from agentcore.simulation.show.models import (
    PublishStatus,
    QuizSettlement,
    QuizSubmission,
    ShowEpisodeMeta,
)

_lock = Lock()
_episodes: dict[str, ShowEpisodeMeta] = {}
_manifests: dict[str, EpisodeManifest] = {}
_quiz_answers: dict[str, str] = {}  # episode_id → answer agent_id
_quiz_monologues: dict[str, tuple[str, str]] = {}  # episode_id → (who, text)
_submissions: dict[str, QuizSubmission] = {}  # user_id:episode_id


def reset_catalog() -> None:
    with _lock:
        _episodes.clear()
        _manifests.clear()
        _quiz_answers.clear()
        _quiz_monologues.clear()
        _submissions.clear()


def register_produced(
    *,
    meta: ShowEpisodeMeta,
    manifest: EpisodeManifest,
    quiz_answer: str | None = None,
    monologue: tuple[str, str] | None = None,
) -> ShowEpisodeMeta:
    with _lock:
        _episodes[meta.episode_id] = meta
        _manifests[meta.episode_id] = manifest
        if quiz_answer:
            _quiz_answers[meta.episode_id] = quiz_answer
        elif manifest.quiz:
            _quiz_answers[meta.episode_id] = manifest.quiz.answer
        if monologue:
            _quiz_monologues[meta.episode_id] = monologue
        elif manifest.reveal and manifest.reveal.answer_overlay_id:
            # Pull monologue text from overlays if present.
            for seg in manifest.segments:
                for ov in seg.overlays:
                    if ov.get("id") == manifest.reveal.answer_overlay_id:
                        _quiz_monologues[meta.episode_id] = (
                            str(ov.get("who") or ""),
                            str(ov.get("text") or ""),
                        )
                        break
        return meta


def list_episodes(season_id: str | None = None) -> list[ShowEpisodeMeta]:
    with _lock:
        rows = list(_episodes.values())
    if season_id:
        rows = [r for r in rows if r.season_id == season_id]
    return sorted(rows, key=lambda r: r.episode_no)


def get_meta(episode_id: str) -> ShowEpisodeMeta | None:
    with _lock:
        return _episodes.get(episode_id)


def get_manifest(episode_id: str, *, require_published: bool = False) -> EpisodeManifest | None:
    with _lock:
        meta = _episodes.get(episode_id)
        if meta is None:
            return None
        if require_published and meta.publish_status != "published":
            return None
        return _manifests.get(episode_id)


def set_publish_status(episode_id: str, status: PublishStatus) -> ShowEpisodeMeta:
    with _lock:
        meta = _episodes.get(episode_id)
        if meta is None:
            raise KeyError(episode_id)
        updated = meta.model_copy(update={"publish_status": status})
        _episodes[episode_id] = updated
        return updated


def submit_quiz(submission: QuizSubmission) -> QuizSettlement:
    with _lock:
        meta = _episodes.get(submission.episode_id)
        if meta is None:
            raise KeyError(submission.episode_id)
        answer = _quiz_answers.get(submission.episode_id, "")
        mono = _quiz_monologues.get(submission.episode_id)
        key = f"{submission.user_id}:{submission.episode_id}"
        _submissions[key] = submission
        return QuizSettlement(
            correct=submission.guess == answer,
            guess=submission.guess,
            answer=answer,
            monologue=mono[1] if mono else None,
            monologue_who=mono[0] if mono else None,
        )


def load_from_produce_dir(path: Path, *, publish_status: PublishStatus = "draft") -> ShowEpisodeMeta:
    """Load artifacts written by ``produce_episode().write``."""
    run = json.loads((path / "run.json").read_text(encoding="utf-8"))
    manifest_raw = json.loads((path / "episode-manifest.json").read_text(encoding="utf-8"))
    manifest = EpisodeManifest.model_validate(manifest_raw)
    episode_id = f"{run.get('run_id', manifest.run_id)}-ep{manifest.episode_no}"
    meta = ShowEpisodeMeta(
        episode_id=episode_id,
        season_id=manifest.season,
        episode_no=manifest.episode_no,
        title=manifest.title,
        run_id=manifest.run_id,
        tick_start=manifest.tick_range.start,
        tick_end=manifest.tick_range.end,
        publish_status=publish_status,
        tagline=manifest.tagline,
        quiz_focus=manifest.quiz.focus if manifest.quiz else None,
    )
    return register_produced(meta=meta, manifest=manifest)
