from app.services.analysis.rules.result_models import (
    VideoAnalysisResult,
    VideoArticleResult,
)
from app.services.analysis.rules.screenplay_results import (
    ScreenplayAnalysisResult,
    ScreenplayRewriteResult,
)

type AnalysisResult = (
    VideoAnalysisResult
    | VideoArticleResult
    | ScreenplayAnalysisResult
    | ScreenplayRewriteResult
)
