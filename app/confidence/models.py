from pydantic import BaseModel


class ConfidenceFactors(BaseModel):
    data_quality: float
    data_completeness: float
    anomaly_strength: float
    rag_similarity: float
    historical_support: float
    evidence_coverage: float
    data_recency: float


class ConfidenceScore(BaseModel):
    score: int  # 0-100
    band: str  # "low" | "medium" | "high"
    factors: ConfidenceFactors
