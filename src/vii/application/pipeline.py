"""End-to-end analysis pipeline: ingest → understand → transcribe → claims → search → assess → report."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Callable

from vii.config import Settings
from vii.errors import ProviderConfigurationError, ProviderError
from vii.domain.enums import (
    AcquisitionMethod, ClaimKind, ClaimStatus, JobStatus, SearchMethod, SourceKind, StageName,
)
from vii.domain.schemas import (
    AnalysisCreate, ClaimIn, MediaOrigin, OriginalityResult, Transcript, VideoUnderstanding,
)
from vii.evidence import retrieval
from vii.integrity import originality as orig_mod
from vii.integrity import provenance as prov_mod
from vii.media import ffmpeg as ffmpeg_mod
from vii.media import ingestion
from vii.media.hashing import sha256_file
from vii.meta import response_parser as rp
from vii.meta.client import MetaClient
from vii.meta.video import VIDEO_ANALYSIS_INSTRUCTIONS, build_file_id_payload, build_url_payload
from vii.meta.transcription import transcribe_audio
from vii.persistence.db import make_engine
from vii.persistence.repositories import AnalysisRepo, JobRepo
from vii.verification import assessment as assess_mod
from vii.verification import claims as claims_mod

log = logging.getLogger("vii.pipeline")
ProgressCb = Callable[[str, str, str], None]  # (job_id, status, message)


def _noop(job_id: str, status: str, message: str) -> None:
    log.info("[%s] %s: %s", job_id, status, message)


DEMO_TRANSCRIPT = [
    (0.0, 4.5, "Welcome to this demonstration of the video integrity pipeline.", None),
    (4.5, 9.0, "This is deterministically generated synthetic demo sample content.", None),
    (9.0, 14.0, "No live Meta transcription was performed for this demo.", None),
]
DEMO_UNDERSTANDING = {
    "summary": ("SYNTHETIC DEMO (not real analysis): a presenter introduces the video-integrity "
                "pipeline in front of a neutral background. No live Meta video understanding "
                "was performed."),
    "events": ["Presenter introduces the pipeline", "Sample chart shown on screen"],
    "visual_observations": ["Single speaker, medium shot", "Neutral studio background"],
    "on_screen_text": ["Video Integrity Intelligence — synthetic demo"],
    "entities": {"people": ["demo presenter"], "organizations": [], "objects": ["chart"], "locations": []},
    "factual_claims": [
        {"text": "The Eiffel Tower is 330 metres tall.", "start_s": 2.0, "end_s": 5.0},
        {"text": "The video claims water boils at 90 degrees Celsius at sea level.", "start_s": 6.0, "end_s": 9.0},
        {"text": "I think this is the best demo ever made.", "start_s": 10.0, "end_s": 12.0},
    ],
    "ambiguous_statements": ["Presenter gestures toward an unlabeled chart"],
    "open_questions": ["What is the original source of the chart shown?"],
}


def demo_understanding() -> VideoUnderstanding:
    """Synthetic fixture for explicit demo mode only (VII_DEMO_MODE / demo=true).

    Never used as a fallback: the default online path raises
    ProviderConfigurationError when no provider is configured instead.
    """
    import json as _json
    vu = rp.parse_video_json(_json.dumps(DEMO_UNDERSTANDING),
                             raw="(synthetic demo fixture)", offline=True)
    return vu


class Pipeline:
    def __init__(self, settings: Settings, session_factory=None):
        self.settings = settings
        self.Session = session_factory or __import__("vii.persistence.db", fromlist=["init_db"]).init_db(
            settings.database_url, settings.storage_dir)
        self.client = MetaClient(settings.effective_api_key, settings.meta_base_url,
                                 settings.meta_model, settings.request_timeout_s,
                                 settings.max_retries, settings.meta_transcription_model)

    # -- public API (used by UI + FastAPI) ---------------------------------
    def create_job(self, req: AnalysisCreate, consumer: str = "default") -> str:
        # Stored in the legacy `offline` column, which now means: this job was
        # explicitly opted into synthetic demo mode. Never set implicitly.
        demo = req.demo_requested or self.settings.demo_enabled
        if not demo and not self.settings.live_mode:
            raise ProviderConfigurationError(
                "MODEL_API_KEY is not configured: provider-backed analysis is "
                "unavailable. Set MODEL_API_KEY, or explicitly opt into "
                "synthetic demo mode (VII_DEMO_MODE=true or demo=true).")
        with self.Session() as db:
            job = JobRepo(db).create(req.title or "Untitled analysis",
                                     req.source.kind.value,
                                     req.source.url or req.source.local_path or "",
                                     demo, consumer or "default")
            return job.id

    def run(self, job_id: str, progress: ProgressCb | None = None) -> dict:
        """Run a job; any failure marks it FAILED before propagating.

        A job is reported succeeded only after every required provider
        operation succeeded (or, in explicit demo mode, after the synthetic
        fixture pipeline completed and is labeled as such)."""
        try:
            return self._run(job_id, progress)
        except Exception as e:
            try:
                with self.Session() as db:
                    jobs = JobRepo(db)
                    job = jobs.get(job_id)
                    if job is not None and str(job.status) != str(JobStatus.SUCCEEDED):
                        jobs.set_status(job, JobStatus.FAILED)
                        jobs.log(job_id, StageName.REPORT,
                                 f"failed: {type(e).__name__}: {str(e)[:400]}", "error")
            except Exception:
                pass  # never mask the original error
            raise

    def _run(self, job_id: str, progress: ProgressCb | None = None) -> dict:
        cb = progress or _noop
        st, repo = self.settings, None
        with self.Session() as db:
            jobs, repo = JobRepo(db), AnalysisRepo(db)
            job = jobs.get(job_id)
            if job is None:
                raise ValueError(f"unknown job {job_id}")
            # Idempotency: re-running a succeeded job must not duplicate
            # claims/evidence/assessments. Return the persisted report payload.
            if str(job.status) == str(JobStatus.SUCCEEDED):
                existing = repo.report_payload(job_id, "json")
                if existing is not None:
                    return existing
            demo = bool(job.offline) or st.demo_enabled
            if not demo and not st.live_mode:
                raise ProviderConfigurationError(
                    "MODEL_API_KEY is not configured: provider-backed analysis "
                    "is unavailable. Set MODEL_API_KEY, or explicitly opt into "
                    "synthetic demo mode (VII_DEMO_MODE=true or demo=true).")
            ref, kind = job.source_ref, job.source_kind
            jobs.set_status(job, JobStatus.INGESTING)
            cb(job_id, JobStatus.INGESTING, "Validating input…")
            jobs.log(job_id, StageName.INGESTION, f"kind={kind} demo={demo}")

            # ---- A. ingestion ----
            media_path, acquisition, sha, meta, converted = self._ingest(
                job_id, kind, ref, demo, jobs, repo, cb)

            # ---- B. native video understanding ----
            jobs.set_status(job, JobStatus.UNDERSTANDING_VIDEO)
            cb(job_id, JobStatus.UNDERSTANDING_VIDEO, "Understanding video…")
            jobs.log(job_id, StageName.VIDEO_UNDERSTANDING, f"method={acquisition} demo={demo}")
            vu = self._understand(job_id, kind, ref, media_path, acquisition, demo, repo, jobs)

            # ---- C. transcription ----
            jobs.set_status(job, JobStatus.TRANSCRIBING)
            cb(job_id, JobStatus.TRANSCRIBING, "Transcribing audio…")
            tr = self._transcribe(job_id, media_path, demo, repo, jobs)

            # ---- D. claim extraction ----
            jobs.set_status(job, JobStatus.EXTRACTING_CLAIMS)
            all_claims = claims_mod.extract(vu)
            factual = [c for c in all_claims if c.kind == ClaimKind.FACTUAL]
            jobs.log(job_id, StageName.CLAIM_EXTRACTION,
                     f"{len(factual)} factual / {len(all_claims)} total claims")
            for i, c in enumerate(all_claims):
                # Job-scoped IDs: Claim.id is a global primary key, so bare
                # per-job counters (c001, c002, ...) collide on the second job
                # with an IntegrityError. Prefixing with job_id keeps IDs stable,
                # unique, and traceable to their owning analysis.
                cid = f"{job_id}_c{i+1:03d}"
                c.__dict__["_id"] = cid
                repo.add_claim(job_id, cid, c.text, c.kind.value, c.start_s, c.end_s)

            # ---- E+F+G. search + validate + assess ----
            jobs.set_status(job, JobStatus.SEARCHING)
            assessments = []
            for c in all_claims:
                cid = c.__dict__["_id"]
                cb(job_id, JobStatus.SEARCHING, f"Searching evidence for {cid}…")
                if c.kind != ClaimKind.FACTUAL:
                    a = assess_mod.ClaimAssessmentIn if False else None
                    from vii.domain.schemas import ClaimAssessmentIn
                    a = ClaimAssessmentIn(claim_id=cid, status=ClaimStatus.UNVERIFIABLE,
                                          explanation=f"Non-factual statement ({c.kind}); not subject to evidence verification.",
                                          limitations="Opinion/satire/prediction/subjective content.",
                                          method="rules")
                else:
                    res = retrieval.search_claim(retrieval.claim_query(c.text), cid, st,
                                                 None if demo else self.client)
                    for r in res["results"]:
                        repo.add_evidence(job_id, cid, r.url, r.title, r.snippet,
                                          r.publisher or "", r.method.value, res["response_id"])
                    for cit in res["citations"]:
                        repo.add_citation(job_id, cid, cit.url, cit.cited_span,
                                          cit.start_index, cit.end_index, res["response_id"])
                    repo.add_search_session(f"ss_{uuid.uuid4().hex[:10]}", job_id, cid,
                                            retrieval.claim_query(c.text),
                                            res["response_id"], res["offline"])
                    jobs.log(job_id, StageName.WEB_SEARCH,
                             f"{cid}: performed={res['performed']} results={len(res['results'])} "
                             f"citations={len(res['citations'])} {res['note']}")
                    a = assess_mod.assess(c, res["results"], res["citations"], res["offline"])
                    a.claim_id = cid
                repo.add_assessment(cid, a.status.value, a.explanation, a.evidence_urls,
                                    a.excerpts, a.contradictions, a.confidence,
                                    a.limitations, a.method)
                assessments.append((c, a))

            # ---- H+I. origin + originality ----
            jobs.set_status(job, JobStatus.ASSESSING)
            origin = prov_mod.assess_origin(meta, acquisition, converted)
            is_local = not str(media_path).startswith(("http://", "https://"))
            try:
                frames = (ffmpeg_mod.sample_frames(
                    media_path, Path(st.storage_dir) / "tmp" / f"{job_id}_frames")
                    if is_local else [])
            except Exception as e:
                jobs.log(job_id, StageName.ORIGINALITY, f"frame sampling failed: {e}", "warning")
                frames = []
            orig = orig_mod.assess_originality(media_path, Path(st.storage_dir) / "corpus", frames)

            # ---- J. report ----
            jobs.set_status(job, JobStatus.REPORTING)
            payload = self._report(job_id, job.title, vu, tr, all_claims, assessments,
                                   origin, orig, demo, repo, jobs)
            jobs.set_status(job, JobStatus.SUCCEEDED)
            cb(job_id, JobStatus.SUCCEEDED, "Analysis complete.")
            return payload

    # -- stages -------------------------------------------------------------
    def _ingest(self, job_id, kind, ref, demo, jobs, repo, cb):
        from vii.domain.schemas import AnalysisCreate as _AC
        st = self.settings
        if kind == SourceKind.PUBLIC_URL:
            info = ingestion.validate_source(
                _AC(source={"kind": "public_url", "url": ref}).source,
                st.max_upload_mb, Path(st.storage_dir))
            from vii.media import social as social_mod
            route = social_mod.resolution_plan(ref)
            if route["strategy"] == "invalid":
                jobs.log(job_id, StageName.INGESTION, f"rejected URL: {route['note']}", "error")
                raise ValueError(route["note"])
            if demo:
                # Explicit synthetic demo: record recognition, behave as native URL.
                repo.add_source(job_id, kind, ref, "",
                                {"host": info["host"], **{k: route[k] for k in
                                 ("platform", "kind", "strategy")}, "demo": True})
                return ref, AcquisitionMethod.NATIVE_URL, "", {"url": ref}, False
            if route["strategy"] == "native_url":
                repo.add_source(job_id, kind, ref, "",
                                {"host": info["host"], **{k: route[k] for k in
                                 ("platform", "kind", "strategy")}})
                jobs.log(job_id, StageName.INGESTION,
                         f"direct media URL ({route['platform']}): native video input")
                return ref, AcquisitionMethod.NATIVE_URL, "", {"url": ref}, False
            # Page URL: authorized platform API first, else require local upload.
            # A page permalink is NEVER video input: both ok AND a usable
            # media_url are required, else the post metadata is recorded and
            # a local upload is required.
            plat = self._platform_acquire(job_id, ref, route, jobs, repo)
            media_url = (plat.get("media_url") or "").strip()
            if plat["ok"] and self._media_url_usable(media_url):
                repo.add_source(job_id, kind, ref, "",
                                {"host": info["host"], "platform": plat["platform"],
                                 "kind": route["kind"], "media_id": plat.get("media_id", ""),
                                 "canonical_url": plat.get("permalink", media_url),
                                 "media_url": media_url,
                                 "auth_method": plat["auth_method"],
                                 "api_status": plat["status"],
                                 "media_binary_acquired": True})
                jobs.log(job_id, StageName.INGESTION,
                         f"platform API acquired media ({plat['platform']}/{plat['auth_method']})")
                return media_url, AcquisitionMethod.PLATFORM_API, "", {"url": media_url}, False
            if plat["ok"]:
                # API confirmed the post exists but returned no usable media binary.
                jobs.log(job_id, StageName.INGESTION,
                         f"platform API returned no media binary "
                         f"({plat['platform']}/{plat.get('auth_method')}); refusing page "
                         "permalink as video input - local upload required", "error")
                repo.add_source(job_id, kind, ref, "",
                                {"host": info["host"], "platform": route["platform"],
                                 "kind": route["kind"], "media_id": plat.get("media_id", ""),
                                 "canonical_url": plat.get("permalink", ""),
                                 "auth_method": plat.get("auth_method", ""),
                                 "api_status": plat.get("status", 0),
                                 "media_binary_acquired": False,
                                 "error": "Authorized API confirmed the post but provided no "
                                          "downloadable media binary."})
                raise ValueError(
                    f"Cannot analyze this {route['platform']} {route['kind']} link automatically: "
                    "the authorized platform API confirmed the post exists but did not return "
                    "its video media. Please upload the video file directly instead.")
            jobs.log(job_id, StageName.INGESTION,
                     f"platform API could not return video: {plat['error']}", "error")
            repo.add_source(job_id, kind, ref, "",
                            {"host": info["host"], "platform": route["platform"],
                             "kind": route["kind"], "auth_method": plat.get("auth_method", ""),
                             "api_status": plat.get("status", 0),
                             "media_binary_acquired": False, "error": plat["error"]})
            raise ValueError(
                f"Cannot analyze this {route['platform']} {route['kind']} link automatically: "
                f"{plat['error']} Please upload the video file directly instead.")
        info = ingestion.validate_source(
            AnalysisCreate(source={"kind": "local_file", "local_path": ref}).source,
            st.max_upload_mb, Path(st.storage_dir))
        sha = sha256_file(info["path"])
        usable, converted, usable_sha = ingestion.ensure_mp4(
            info["path"], Path(st.storage_dir), st.ffmpeg_bin, sha)
        try:
            meta = ffmpeg_mod.metadata_summary(ffmpeg_mod.probe(usable, st.ffprobe_bin))
            dur = meta.get("duration_s", 0)
            if dur > st.max_video_seconds:
                raise ValueError(f"video too long: {dur:.0f}s > {st.max_video_seconds}s")
        except ValueError:
            raise
        except Exception as e:
            jobs.log(job_id, StageName.INGESTION, f"probe failed ({e}); continuing", "warning")
            meta = {"format": "unknown", "duration_s": 0, "size_bytes": 0}
        repo.add_source(job_id, kind, ref, sha,
                        {"container": meta, "converted": converted, "usable_sha": usable_sha})
        meth = AcquisitionMethod.FILE_ID if not demo else AcquisitionMethod.LOCAL_UPLOAD
        return str(usable), meth, sha, meta, converted

    @staticmethod
    def _media_url_usable(media_url: str) -> bool:
        """A media_url is usable only when it is a direct http(s) media file,
        never an HTML page permalink."""
        from urllib.parse import urlparse
        if not media_url or not media_url.startswith(("http://", "https://")):
            return False
        try:
            host = (urlparse(media_url).hostname or "").lower()
        except Exception:
            return False
        from vii.media import social as social_mod
        if host in social_mod.INSTAGRAM_HOSTS or host in social_mod.FACEBOOK_HOSTS:
            return False
        return True

    def _platform_acquire(self, job_id, ref, route, jobs, repo) -> dict:
        """Authorized platform retrieval only. Never downloads via unofficial tools."""
        from vii.platforms import facebook as fb_mod
        from vii.platforms import instagram as ig_mod
        platform = route["platform"]
        if platform == "instagram":
            res = ig_mod.fetch_media(ref, self.settings.instagram_token)
        elif platform == "facebook":
            res = fb_mod.fetch_media(ref, self.settings.facebook_page_token)
        else:
            res = {"ok": False, "platform": platform,
                   "error": f"No authorized API integration for platform '{platform}'; "
                            "provide a direct media URL or a local MP4 upload.",
                   "auth_method": "none", "status": 0,
                   "media_binary_acquired": False}
        jobs.log(job_id, StageName.INGESTION,
                 f"platform={res.get('platform')} auth={res.get('auth_method')} "
                 f"status={res.get('status')} ok={res.get('ok')}")
        return res

    def _understand(self, job_id, kind, ref, media_path, acquisition, demo, repo, jobs):
        st = self.settings
        if demo:
            repo.add_meta_request(job_id, "video_understanding", "synthetic-demo-fixture",
                                  {"demo": True}, "demo", True)
            return demo_understanding()
        if kind == SourceKind.PUBLIC_URL:
            payload = build_url_payload(ref, st.meta_model)
        else:
            up = self.client.upload_video(media_path)  # purpose="user_data"
            jobs.log(job_id, StageName.VIDEO_UNDERSTANDING, f"files.upload file_id={up['file_id']}")
            repo.add_meta_request(job_id, "files_upload", st.meta_model,
                                  {"purpose": "user_data"}, up["file_id"], False)
            payload = build_file_id_payload(up["file_id"], st.meta_model)
        resp = self.client.responses_create(payload)
        repo.add_meta_request(job_id, "video_understanding", st.meta_model,
                              {"model": st.meta_model, "mode": acquisition},
                              resp.get("id", ""), False)
        text = rp.output_text(resp)
        return rp.parse_video_json(text, raw=text, offline=False)

    def _transcribe(self, job_id, media_path, demo, repo, jobs) -> Transcript:
        st = self.settings
        if demo or not media_path or str(media_path).startswith("http"):
            if demo:
                from vii.domain.schemas import TranscriptSegment
                segs = [TranscriptSegment(start_s=a, end_s=b, text=t, speaker=sp)
                        for a, b, t, sp in DEMO_TRANSCRIPT]
                tr = Transcript(segments=segs, language="en",
                                engine="synthetic-demo-fixture", offline=True)
            else:
                tr = Transcript(segments=[], engine="url-transcription-unavailable",
                                offline=False, language="unknown")
                jobs.log(job_id, StageName.TRANSCRIPTION,
                         "URL media: transcription skipped (no local audio)", "warning")
            for s_ in tr.segments:
                repo.add_transcript_segment(job_id, s_.start_s, s_.end_s, s_.text,
                                            s_.speaker or "", tr.engine)
            jobs.log(job_id, StageName.TRANSCRIPTION,
                     f"engine={tr.engine} segments={len(tr.segments)} offline={tr.offline}")
            return tr
        tr = transcribe_audio(media_path, st, self.client)
        for s_ in tr.segments:
            repo.add_transcript_segment(job_id, s_.start_s, s_.end_s, s_.text,
                                        s_.speaker or "", tr.engine)
        jobs.log(job_id, StageName.TRANSCRIPTION,
                 f"engine={tr.engine} segments={len(tr.segments)} offline={tr.offline}")
        return tr

    def _report(self, job_id, title, vu, tr, all_claims, assessments, origin, orig,
                demo, repo, jobs) -> dict:
        from vii.reports.exporter import build_payload, export
        claims_out, sources_out = [], []
        for c, a in assessments:
            claims_out.append({"id": c.__dict__.get("_id", ""), "text": c.text,
                               "kind": c.kind.value, "start_s": c.start_s, "end_s": c.end_s,
                               "status": a.status.value, "explanation": a.explanation,
                               "evidence": a.evidence_urls, "excerpts": a.excerpts,
                               "contradictions": a.contradictions, "confidence": a.confidence,
                               "limitations": a.limitations, "method": a.method})
        for e in repo.evidence_for_job(job_id):
            sources_out.append({"url": e.url, "title": e.title, "snippet": e.snippet,
                                "publisher": e.publisher, "method": e.method,
                                "claim_id": e.claim_id})
        dims = {
            "claim_verification": [{"id": c["id"], "status": c["status"]} for c in claims_out],
            "supporting_contradicting_evidence": sources_out,
            "media_origin": origin.model_dump(),
            "originality": orig.model_dump(),
            "uncertainty_limitations": [
                "Model descriptions of video content are not evidence of truth.",
                ("SYNTHETIC DEMO: deterministic fixtures were used; this is not "
                 "real provider-backed analysis." if demo else
                 "Provider-backed analysis: claims are assessed only from "
                 "retrieved, cited evidence."),
            ] + ([f"Transcript engine: {tr.engine}"] if tr.offline or "error" in tr.engine else []),
        }
        errors = [{"stage": l.stage, "message": l.message}
                  for l in jobs.logs(job_id) if l.level in ("warning", "error")]
        payload = build_payload(job_id, title, dims, claims_out, sources_out, errors,
                                dims["uncertainty_limitations"], demo)
        for fmt in ("json", "markdown"):
            path = export(payload, Path(self.settings.storage_dir) / "exports", fmt)
            repo.add_report(job_id, fmt, str(path), payload)
            jobs.log(job_id, StageName.REPORT, f"exported {fmt}: {path.name}")
        return payload
