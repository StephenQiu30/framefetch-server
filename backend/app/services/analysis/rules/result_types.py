from app.services.analysis.rules.content_document import ContentDocumentResult
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
    ContentDocumentResult
    | VideoAnalysisResult
    | VideoArticleResult
    | ScreenplayAnalysisResult
    | ScreenplayRewriteResult
    | StructuredReportResult
)
