"""wwt CLI 앱 - typer 기반 명령어 인터페이스."""

import typer

app = typer.Typer(
    name="wwt",
    help="whatwasthat - AI 대화 기억 솔루션",
)


@app.command()
def init() -> None:
    """WWT 초기 설정 (Ollama 모델 다운로드 + DB 초기화)."""
    pass


@app.command()
def ingest(path: str = typer.Argument(help="대화 로그 경로")) -> None:
    """대화 로그를 Knowledge Graph로 적재."""
    pass


@app.command()
def search(query: str = typer.Argument(help="검색 쿼리")) -> None:
    """과거 대화에서 관련 기억 검색."""
    pass


@app.command()
def watch() -> None:
    """백그라운드 데몬 - 새 대화 자동 감지 및 추출."""
    pass
