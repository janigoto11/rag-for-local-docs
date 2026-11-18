import logging
import time
from pathlib import Path
from typing import Annotated

import psycopg
import typer
from psycopg.conninfo import conninfo_to_dict
from rich.console import Console
from rich.table import Table

from .config import Settings, get_settings
from .db import SchemaMismatchError, connect, ensure_schema
from .db import reset as reset_db
from .embeddings import EmbedderUnavailableError, check_embedder, get_embedder
from .evaluation import run_eval, summarize
from .indexer import index_root
from .reranking import Reranker, RerankerUnavailableError, get_reranker
from .search import hybrid_search

app = typer.Typer(no_args_is_help=True, help="Paikallinen RAG omille dokumenteillesi.")
console = Console()


def _fail(message: str, detail: str | None = None) -> typer.Exit:
    console.print(f"[red]Virhe:[/] {message}")
    if detail:
        console.print(f"[dim]{detail}[/]")
    return typer.Exit(1)


def _connect(settings: Settings, ensure: bool = True) -> psycopg.Connection:
    try:
        conn = connect(settings)
    except psycopg.OperationalError as e:
        info = conninfo_to_dict(settings.database_url)
        where = f"{info.get('host', 'localhost')}:{info.get('port', 5432)}/{info.get('dbname', '')}"
        raise _fail(
            f"Tietokantaan ei saada yhteyttä ({where}). "
            "Käynnistä palvelut: scripts/services.sh start",
            str(e).splitlines()[0],
        ) from e
    if ensure:
        try:
            ensure_schema(conn, settings)
        except SchemaMismatchError as e:
            raise _fail(str(e)) from e
    return conn


def _setup(need_embedder: bool = True):
    settings = get_settings()
    conn = _connect(settings)
    embedder = get_embedder(settings)
    if need_embedder:
        try:
            check_embedder(embedder, settings)
        except EmbedderUnavailableError as e:
            raise _fail(str(e)) from e
    return settings, conn, embedder


def _reranker(settings: Settings) -> Reranker | None:
    try:
        return get_reranker(settings)
    except RerankerUnavailableError as e:
        raise _fail(str(e)) from e


def _describe_search(settings: Settings, reranker: Reranker | None) -> str:
    parts = [f"embedding={settings.embedding_model}"]
    parts.append(f"reranker={reranker.model if reranker else 'ei'}")
    parts.append(f"täytesanasuodatus={'päällä' if settings.fts_stopwords else 'pois'}")
    return " ".join(parts)


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)


@app.command()
def index(paths: Annotated[list[Path], typer.Argument(help="Indeksoitavat hakemistot")]) -> None:
    """Indeksoi (tai päivittää inkrementaalisesti) yhden tai useamman hakemiston."""
    settings, conn, embedder = _setup()
    for root in paths:
        if not root.is_dir():
            console.print(f"[red]Not a directory:[/] {root}")
            raise typer.Exit(1)
        console.print(f"Indexing [bold]{root.expanduser().resolve()}[/]")
        stats = index_root(
            conn,
            root,
            settings,
            embedder,
            on_progress=lambda _, p: console.print(f"  [dim]{p}[/]"),
        )
        console.print(
            f"  scanned={stats.scanned} indexed={stats.indexed} unchanged={stats.unchanged} "
            f"skipped={stats.skipped} removed={stats.removed} chunks={stats.chunks}"
        )
        for path, err in stats.errors:
            console.print(f"  [red]error[/] {path}: {err}")


@app.command()
def search(
    query: str,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 8,
    prefix: Annotated[
        str | None, typer.Option(help="Vain tämän polun alla olevat tiedostot")
    ] = None,
    full: Annotated[bool, typer.Option(help="Näytä palojen koko sisältö")] = False,
    timing: Annotated[bool, typer.Option("--timing", help="Näytä hakuvaiheiden kestot")] = False,
) -> None:
    """Ajaa hybridihaun ja tulostaa osumat."""
    settings, conn, embedder = _setup()
    start = time.perf_counter()
    reranker = _reranker(settings)
    load_time = time.perf_counter() - start
    timings: dict[str, float] = {}
    hits = hybrid_search(conn, embedder, settings, query, limit, prefix, reranker, timings)
    for i, h in enumerate(hits, 1):
        ranks = f"vec={h.vec_rank or '-'} fts={h.fts_rank or '-'} rrf={h.score:.4f}"
        if h.rerank_score is not None:
            ranks += f" rerank={h.rerank_score:.3f}"
        console.print(f"[bold]{i}. {h.path}[/] [dim]#{h.chunk_index} {ranks}[/]")
        if h.heading_path:
            console.print(f"   [cyan]{h.heading_path}[/]")
        text = h.content if full else h.content[:300].replace("\n", " ") + "..."
        console.print(f"   {text}\n")
    if timing:
        labels = {"embedding": "embedding", "database": "tietokanta", "rerank": "reranker"}
        parts = [f"{labels[k]} {v:.2f} s" for k, v in timings.items()]
        if reranker:
            n = settings.rerank_candidates
            parts.append(f"(rerankerin lataus {load_time:.2f} s, {n} ehdokasta)")
        console.print(f"[dim]Kestot: {', '.join(parts)}[/]")


@app.command()
def prepare() -> None:
    """Lataa käytössä olevat mallit valmiiksi, jottei ensimmäinen haku joudu odottamaan."""
    settings = get_settings()
    if settings.reranker == "none":
        console.print("Reranker ei ole käytössä, ladattavaa ei ole.")
        return
    console.print(f"Ladataan reranker-malli {settings.rerank_model}...")
    reranker = _reranker(settings)
    reranker.score("testi", ["testi"])
    console.print("Valmis.")


@app.command()
def stats() -> None:
    """Näyttää indeksin tilastot."""
    _, conn, _ = _setup(need_embedder=False)
    row = conn.execute(
        "SELECT (SELECT count(*) FROM documents) AS docs, (SELECT count(*) FROM chunks) AS chunks,"
        " (SELECT value FROM meta WHERE key = 'embedding_model') AS model"
    ).fetchone()
    console.print(f"documents={row['docs']} chunks={row['chunks']} model={row['model']}")
    table = Table("parser", "documents")
    for r in conn.execute("SELECT parser, count(*) AS n FROM documents GROUP BY parser"):
        table.add_row(r["parser"], str(r["n"]))
    console.print(table)


@app.command()
def reset(yes: Annotated[bool, typer.Option("--yes", "-y")] = False) -> None:
    """Poistaa kaiken indeksoidun datan (tarpeen embedding-mallin vaihdon jälkeen)."""
    if not yes and not typer.confirm("Drop all indexed documents and chunks?"):
        raise typer.Abort()
    reset_db(_connect(get_settings(), ensure=False))
    console.print("Index dropped.")


@app.command("eval")
def eval_cmd(
    file: Annotated[Path, typer.Argument()] = Path("evals/questions.yaml"),
    k: Annotated[int, typer.Option("-k")] = 5,
) -> None:
    """Mittaa haun laatua dokumentti- ja palatasolla (osumaosuus ja MRR k:n parhaan joukossa)."""
    settings, conn, embedder = _setup()
    reranker = _reranker(settings)
    console.print(f"[dim]{_describe_search(settings, reranker)}[/]")
    results = run_eval(conn, embedder, settings, file, k, reranker)

    def fmt(rank: int | None, applicable: bool = True) -> str:
        if not applicable:
            return "-"
        return str(rank) if rank else "[red]miss[/]"

    table = Table("dok", "pala", "kysymys", "paras dokumentti")
    for r in results:
        top = Path(r.top_paths[0]).name if r.top_paths else "-"
        table.add_row(fmt(r.rank), fmt(r.chunk_rank, r.has_expected_text), r.question, top)
    console.print(table)
    s = summarize(results)
    console.print(
        f"dokumentit: questions={s['questions']} hit@{k}={s['hit_rate']:.2f} mrr@{k}={s['mrr']:.2f}"
    )
    if s["chunk_questions"]:
        console.print(
            f"palat:      questions={s['chunk_questions']} hit@{k}={s['chunk_hit_rate']:.2f} "
            f"mrr@{k}={s['chunk_mrr']:.2f}"
        )
