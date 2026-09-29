from app.services.analysis.rules.result_models import (
    VideoAnalysisResult,
    VideoArticleResult,
)
from app.services.analysis.rules.screenplay_results import (
    ScreenplayAnalysisResult,
    ScreenplayRewriteResult,
)
from app.services.analysis.rules.structured_report import StructuredReportResult

type AnalysisResult = (
    VideoAnalysisResult
    | VideoArticleResult
    | ScreenplayAnalysisResult
    | ScreenplayRewriteResult
    | StructuredReportResult
)
