"""Weekly knowledge-gap digest (batch-only).

Aggregates the last N days of ``knowledge_gaps`` rows plus weak-outcome
stats from ``audit_log`` and emails a summary to every active admin via
the shared mailer (console fallback when SMTP is unconfigured — never
raises).

Batch-only by design (rule 5): invoked from
``scripts/gap_digest.py`` behind a systemd timer, never from a request
handler. No LLM, no generated prose — every line of the digest is a
count or a verbatim query string taken from the database.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GapDigestConfig:
    """Digest window/size knobs (rule 7: configuration, not constants)."""

    window_days: int = 7
    top_n: int = 10          # how many top gap queries to include
    digest_type: str = "gap_digest"
    subject_prefix: str = "Asto weekly knowledge-gap digest"


DEFAULT_DIGEST = GapDigestConfig()


def collect_digest(conn, config: GapDigestConfig | None = None) -> dict:
    """Aggregate the digest window. Read-only; caller owns the transaction.

    Returns ``{"window_days", "total_gaps", "distinct_queries",
    "top_queries": [{"query", "times", "last_seen"}], "weak": {...}}``.
    """
    config = config or DEFAULT_DIGEST
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS total, COUNT(DISTINCT query) AS distinct_q "
            "FROM knowledge_gaps "
            "WHERE created_at >= now() - make_interval(days => %s)",
            (config.window_days,),
        )
        totals = cur.fetchone()

        cur.execute(
            "SELECT query, COUNT(*) AS times, MAX(created_at) AS last_seen "
            "FROM knowledge_gaps "
            "WHERE created_at >= now() - make_interval(days => %s) "
            "AND btrim(query) <> '' "
            "GROUP BY query "
            "ORDER BY times DESC, last_seen DESC "
            "LIMIT %s",
            (config.window_days, config.top_n),
        )
        top = [
            {
                "query": r["query"],
                "times": int(r["times"]),
                "last_seen": r["last_seen"],
            }
            for r in cur.fetchall()
        ]

        # Weak-outcome share for the same window (same shape as J5 stats).
        cur.execute(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE outcome IN (%s, %s)) AS weak "
            "FROM audit_log "
            "WHERE created_at >= now() - make_interval(days => %s) "
            "AND outcome IS NOT NULL",
            ("no_answer", "partial", config.window_days),
        )
        weak_row = cur.fetchone()

    weak_total = int(weak_row["total"] or 0)
    weak_count = int(weak_row["weak"] or 0)

    return {
        "window_days": config.window_days,
        "total_gaps": int(totals["total"] or 0),
        "distinct_queries": int(totals["distinct_q"] or 0),
        "top_queries": top,
        "weak": {
            "total": weak_total,
            "count": weak_count,
            "rate": (weak_count / weak_total) if weak_total else 0.0,
        },
    }


def render_digest_text(report: dict) -> tuple[str, str, str]:
    """Render the digest as ``(subject, text, html)``.

    Every content line is either a count or a verbatim logged query.
    """
    window = report["window_days"]
    subject = f"{DEFAULT_DIGEST.subject_prefix} ({report['total_gaps']} gaps, {window}d)"

    lines = [
        f"Knowledge-gap digest for the last {window} day(s).",
        "",
        f"Gaps logged: {report['total_gaps']} "
        f"({report['distinct_queries']} distinct queries)",
        (
            f"Weak outcomes (no answer / partial): "
            f"{report['weak']['count']} of {report['weak']['total']} queries "
            f"({report['weak']['rate']:.0%})"
        ),
    ]
    html_lines = [
        f"<p>Knowledge-gap digest for the last {window} day(s).</p>",
        (
            f"<p>Gaps logged: <strong>{report['total_gaps']}</strong> "
            f"({report['distinct_queries']} distinct queries)<br>"
            f"Weak outcomes (no answer / partial): "
            f"{report['weak']['count']} of {report['weak']['total']} queries "
            f"({report['weak']['rate']:.0%})</p>"
        ),
    ]

    if report["top_queries"]:
        lines.append("", )
        lines.append("Top unanswered questions:")
        html_lines.append("<p><strong>Top unanswered questions:</strong></p><ol>")
        for entry in report["top_queries"]:
            line = f"  {entry['times']}x  {entry['query']}"
            lines.append(line)
            html_lines.append(f"<li>{entry['query']} ({entry['times']}x)</li>")
        html_lines.append("</ol>")
    else:
        lines.append("")
        lines.append("No knowledge gaps recorded in this window.")
        html_lines.append("<p>No knowledge gaps recorded in this window.</p>")

    text = "\n".join(lines)
    html = "".join(html_lines)
    return subject, text, html


def email_digest(conn, report: dict) -> int:
    """Email the digest to every active admin. Returns attempts made.

    Best-effort: uses the shared mailer (never raises); with SMTP
    unconfigured each message is logged to the console instead.
    """
    from app.email.mailer import send_email

    subject, text, html = render_digest_text(report)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT email FROM users "
            "WHERE is_active = true AND role IN ('admin', 'super_admin') "
            "AND email IS NOT NULL"
        )
        rows = cur.fetchall()
    sent = 0
    for row in rows:
        if send_email(row["email"], subject, html, text):
            sent += 1
    return sent
