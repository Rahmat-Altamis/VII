"""Public library client for Video Integrity Intelligence.

This is the supported entry point for downstream applications and a
future CLI. It deliberately exposes only local, provider-independent
operations plus one provider-backed analysis operation:

* Local operations (no network, no database, no provider credentials):
  ``inspect_media``, ``sha256``, ``assess_originality``,
  ``validate_dataset``, and ``capabilities`` (a local configuration
  report; it never contacts a provider).
* Provider-backed operation: ``analyze``. This is the only method that
  may contact an external provider, and only when called. It reuses the
  existing application pipeline, so it uses the configured database and
  storage directory; without a configured API key (and without an
  explicit synthetic-demo opt-in) it raises
  :class:`vii.errors.ProviderConfigurationError` instead of returning
  fabricated results.

Constructing ``VII`` performs no network I/O, opens no database, and
creates no storage directories. Heavier subsystems (application
services, persistence, provider transport) are imported lazily by the
methods that need them, so ``import vii`` stays lightweight.

Integrity results describe what was actually checked (for example,
exact/near-duplicate matches against a local corpus). They never prove
that a video is genuine.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from vii.config import Settings
from vii.domain.schemas import AnalysisCreate, MediaIngestionResult, OriginalityResult
from vii.errors import ProviderConfigurationError

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps import vii light
    from vii.dataset.ingestion import ValidationReport
    from vii.domain.schemas import DeepfakeAssessment


class VII:
    """Client for the VII library.

    Parameters are explicit alternatives to environment configuration.
    Pass either ``settings`` or individual overrides, not both.

    Example:
        >>> from vii import VII
        >>> client = VII(api_key="YOUR_API_KEY")  # doctest: +SKIP
        >>> result = client.analyze("sample.mp4")  # doctest: +SKIP

    ``api_key`` here is the provider key (``MODEL_API_KEY``). It is
    never logged by this class and no request is made until
    ``analyze`` is called.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        settings: Settings | None = None,
        base_url: str | None = None,
        model: str | None = None,
        database_url: str | None = None,
        storage_dir: str | Path | None = None,
        dataset_csv_path: str | Path | None = None,
    ) -> None:
        if settings is not None:
            if any(v is not None for v in (
                    api_key, base_url, model, database_url, storage_dir,
                    dataset_csv_path)):
                raise ValueError(
                    "pass either settings or individual overrides, not both")
            self.settings = settings
        else:
            overrides: dict[str, Any] = {}
            if api_key is not None:
                overrides["MODEL_API_KEY"] = api_key
            if base_url is not None:
                overrides["META_BASE_URL"] = base_url
            if model is not None:
                overrides["META_MODEL"] = model
            if database_url is not None:
                overrides["VII_DATABASE_URL"] = database_url
            if storage_dir is not None:
                overrides["VII_STORAGE_DIR"] = storage_dir
            if dataset_csv_path is not None:
                overrides["DATASET_CSV_PATH"] = dataset_csv_path
            self.settings = Settings(**overrides)
        self._service: Any = None

    # -- local, provider-independent operations ---------------------------

    def inspect_media(self, path: str | Path) -> MediaIngestionResult:
        """Validate, signature-check, and hash one local media file.

        Local only: no provider is contacted, no database is opened,
        and no analysis job is created. Raises typed ``ValueError``
        subclasses from :mod:`vii.errors` for missing, empty,
        oversized, unsupported, signature-mismatched, or over-duration
        media. A duration that cannot be determined locally is reported
        as unknown, never guessed.
        """
        from vii.media.ingestion import inspect_local_media

        s = self.settings
        return inspect_local_media(
            path, s.max_upload_mb, s.max_video_seconds, s.ffprobe_bin)

    def sha256(self, path: str | Path) -> str:
        """Return the SHA-256 hex digest of a local file."""
        from vii.media.hashing import sha256_file

        return sha256_file(path)

    def assess_originality(
        self,
        media_path: str | Path,
        corpus_dir: str | Path | None = None,
        sample_frames: list[Path] | None = None,
    ) -> OriginalityResult:
        """Check a local file against a local comparison corpus.

        Reports the file's SHA-256, an exact-duplicate match, and
        perceptual-hash near-duplicates. ``corpus_dir`` defaults to
        ``<storage_dir>/corpus`` (matching the analysis pipeline); a
        missing corpus simply yields no matches. "No match" means no
        duplicate was found in that corpus, it does not prove the
        media is original or genuine. Remote URLs are not fetched;
        they return an explanatory result with an empty digest.
        """
        from vii.integrity.originality import assess_originality

        corpus = (Path(corpus_dir) if corpus_dir is not None
                  else Path(self.settings.storage_dir) / "corpus")
        return assess_originality(media_path, corpus, sample_frames)

    def assess_forensics(
        self,
        media_path: str | Path,
        sample_frames: list[Path] | None = None,
        audio_path: str | Path | None = None,
    ) -> DeepfakeAssessment:
        """Evaluate local manipulation-forensics signals for a file.

        Local only: no provider is contacted and no job is created.
        Reports categorical forensic signals (frame reuse,
        recompression error, temporal transitions, re-encode/screen
        layer, sensor-noise uniformity, light bias, spectral
        concentration, temporal flicker, audio room tone, provenance
        sparsity) with explicit limitations. It never returns a
        genuine/fake verdict or a probability, and "no signals" does
        not prove the media is authentic. Remote URLs are not fetched;
        they return an ``unavailable`` assessment. ``audio_path`` is an
        optional local WAV for the room-tone signal.
        """
        from vii.integrity.forensics import assess_manipulation

        return assess_manipulation(media_path, sample_frames, None, audio_path)

    def validate_dataset(self, path: str | Path | None = None) -> ValidationReport:
        """Validate a dataset CSV with no side effects.

        Uses the configured dataset path (``DATASET_CSV_PATH``, default
        ``data/dataset.csv``) when ``path`` is omitted. A missing file
        is a normal state reported as ``exists=False``, not an error.
        Loading or validating a dataset never starts video analysis.
        """
        from vii.dataset.ingestion import validate_csv

        target = Path(path) if path is not None else self.settings.dataset_csv_path
        return validate_csv(target)

    def capabilities(self) -> dict:
        """Return the local provider-capability report.

        Configuration only: states such as ``configured_unverified``,
        ``blocked``, or ``disabled`` describe local settings. No
        provider is contacted and no credits are spent.
        """
        from vii.providers.capabilities import provider_capabilities

        return provider_capabilities(self.settings)

    def quick_look(self, path: str | Path, sample_frames: int = 8) -> dict:
        """Fast local pre-screen of one video file (seconds, no provider).

        Samples real frames and runs them through the forensics
        ensemble (frame reuse, recompression error, temporal
        transitions, re-encode/screen layer, sensor-noise uniformity,
        light bias, spectral concentration, temporal flicker, audio
        room tone) plus perceptual-hash originality, media probing,
        and spam-format markers, then returns a plain dict. No job is
        created, no credits are spent, and nothing here is a
        genuine/fake verdict. Errors raise the same typed
        ``ValueError`` subclasses as :meth:`inspect_media`.
        """
        import tempfile as _tempfile
        import time as _time

        from vii.integrity.spam import FORMULA_MARKERS
        from vii.media.ffmpeg import probe as _probe
        from vii.media.ffmpeg import sample_frames as _sample

        started = _time.monotonic()
        info = self.inspect_media(path)
        tmpdir = _tempfile.mkdtemp(prefix="vii_quick_")
        try:
            try:
                frames = _sample(path, tmpdir, max_frames=sample_frames)
            except Exception:
                frames = []
            try:
                probed = _probe(path, self.settings.ffprobe_bin)
                streams = [{k: s.get(k) for k in
                            ("codec_type", "codec_name", "width", "height",
                             "avg_frame_rate", "sample_rate", "channels")}
                           for s in probed.get("streams", [])]
            except Exception:
                streams = []
            try:
                from vii.media.ffmpeg import extract_audio_wav as _wav

                audio = _wav(path, Path(tmpdir) / "forensic.wav",
                             self.settings.ffmpeg_bin, sample_rate=16000,
                             start_s=0.0, end_s=60.0)
            except Exception:
                audio = None
            forensic = self.assess_forensics(path, frames or None,
                                             audio_path=audio)
            orig = self.assess_originality(path, sample_frames=frames or None)
        finally:
            import shutil as _shutil

            _shutil.rmtree(tmpdir, ignore_errors=True)
        file_name = Path(path).name
        markers = [m for m in FORMULA_MARKERS if m in file_name.lower()]
        return {
            "path": str(path),
            "file_name": file_name,
            "size_bytes": info.size_bytes,
            "duration_s": info.duration_s,
            "duration_source": info.duration_source,
            "container": info.container,
            "has_audio": info.has_audio,
            "sha256": info.sha256,
            "streams": streams,
            "frames_sampled": len(frames),
            "forensics": forensic.model_dump(),
            "originality": {
                "exact_duplicate_of": orig.exact_duplicate_of,
                "phash_matches": list(orig.phash_matches or []),
                "notes": orig.notes,
            },
            "filename_markers": markers,
            "elapsed_s": round(_time.monotonic() - started, 2),
            "note": ("Local pre-screen only: fast signals, no provider "
                     "analysis. Full results follow from the pipeline."),
        }

    # -- provider-backed analysis ------------------------------------------

    def _analysis_service(self) -> Any:
        """Lazily build (and cache) the application service.

        Importing and constructing the service opens the configured
        database, so this happens only on the first ``analyze`` call,
        never at client construction or import time.
        """
        if self._service is None:
            from vii.application.services import AnalysisService

            self._service = AnalysisService(self.settings)
        return self._service

    def analyze(
        self,
        source: str | Path | AnalysisCreate,
        *,
        title: str | None = None,
        demo: bool = False,
    ) -> dict:
        """Run one provider-backed analysis and return its report payload.

        ``source`` is a local file path, a public ``http(s)`` media
        URL, or a pre-built :class:`vii.domain.schemas.AnalysisCreate`.
        ``title``/``demo`` must not be combined with a pre-built
        request. ``demo=True`` is an explicit opt-in to the labeled
        synthetic demo; it is never selected implicitly.

        Returns the persisted report payload ``dict`` produced by the
        existing pipeline (five separate assessment dimensions, claims,
        sources, limitations, and operational metadata).

        Raises:
            ProviderConfigurationError: no API key is configured and
                demo mode was not explicitly enabled.
            vii.errors.ProviderError: the provider request failed.
            ValueError: the source is invalid or unsupported.
        """
        if isinstance(source, AnalysisCreate):
            if title is not None or demo:
                raise ValueError(
                    "title/demo must not be combined with an AnalysisCreate source")
            request = source
        else:
            text = str(source)
            if text.startswith(("http://", "https://")):
                source_in: dict[str, Any] = {"kind": "public_url", "url": text}
            else:
                source_in = {"kind": "local_file", "local_path": text}
            request = AnalysisCreate(source=source_in, title=title, demo=demo)
        if not request.demo_requested and not self.settings.demo_enabled \
                and not self.settings.live_mode:
            # Fail before opening the database or creating any job:
            # provider-backed analysis without credentials is a typed
            # configuration error, never a fabricated result.
            raise ProviderConfigurationError(
                "MODEL_API_KEY is not configured: provider-backed analysis is "
                "unavailable. Pass api_key=... to VII(...), set MODEL_API_KEY, "
                "or explicitly opt into synthetic demo mode (demo=True).")
        service = self._analysis_service()
        job_id = service.create(request)
        return service.run(job_id)

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        """Release resources held by the lazily built analysis service.

        Safe to call when no analysis has run (a no-op) and safe to
        call more than once. Local operations remain usable afterwards;
        a later ``analyze`` builds a fresh service.
        """
        service, self._service = self._service, None
        if service is None:
            return
        session = getattr(service, "Session", None)
        engine = None
        if session is not None:
            try:
                engine = session.get_bind()
            except Exception:
                engine = None
        if engine is not None:
            engine.dispose()

    def __enter__(self) -> VII:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        s = self.settings
        return (f"VII(model={s.meta_model!r}, live_mode={s.live_mode}, "
                f"demo_enabled={s.demo_enabled})")
