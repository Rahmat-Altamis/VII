"""Shared enums — five assessment dimensions stay separate (no single real/fake score)."""
from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # keep JSON-friendly
        return self.value


class JobStatus(StrEnum):
    QUEUED = "queued"
    INGESTING = "ingesting"
    UNDERSTANDING_VIDEO = "understanding_video"
    TRANSCRIBING = "transcribing"
    EXTRACTING_CLAIMS = "extracting_claims"
    SEARCHING = "searching"
    ASSESSING = "assessing"
    REPORTING = "reporting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceKind(StrEnum):
    LOCAL_FILE = "local_file"
    PUBLIC_URL = "public_url"


class AcquisitionMethod(StrEnum):
    NATIVE_URL = "native_url"  # Meta input_video with direct media video_url
    PLATFORM_API = "platform_api"  # authorized Instagram Graph / Facebook Page API
    FILE_ID = "file_id"  # Meta Files API upload + file_id reference
    LOCAL_UPLOAD = "local_upload"  # user-supplied file, offline/fallback


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    MIXED_EVIDENCE = "mixed_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNVERIFIABLE = "unverifiable"
    NOT_YET_ANALYZED = "not_yet_analyzed"


class ClaimKind(StrEnum):
    FACTUAL = "factual"
    OPINION = "opinion"
    SATIRE = "satire"
    PREDICTION = "prediction"
    SUBJECTIVE = "subjective"


class SearchMethod(StrEnum):
    META_WEB_SEARCH = "meta_web_search"
    NONE_OFFLINE = "none_offline"


class StageName(StrEnum):
    INGESTION = "ingestion"
    VIDEO_UNDERSTANDING = "video_understanding"
    TRANSCRIPTION = "transcription"
    CLAIM_EXTRACTION = "claim_extraction"
    WEB_SEARCH = "web_search"
    ASSESSMENT = "assessment"
    ORIGIN = "origin"
    ORIGINALITY = "originality"
    REPORT = "report"
