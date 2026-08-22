"""Admin CRUD for pinned answers (curated verbatim response packages).

  GET    /admin/pinned-answers          — list all pins (active + inactive)
  POST   /admin/pinned-answers          — pin a response package
  PATCH  /admin/pinned-answers/{id}     — toggle active / change audience
  DELETE /admin/pinned-answers/{id}     — remove a pin

Pin creation requires the ``response_id`` of a REAL served search (looked
up in ``audit_log``) so every pin traces back to an audited retrieval, and
a structural validation pass (see ``app.response.pinned_answers``) that
only accepts successful document-path packages with verbatim content.
No LLM and no generated text is involved anywhere: a pin replays stored
retrieved values verbatim.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Json
from pydantic import BaseModel, Field

from app.auth.permissions import require_role
from app.db.postgres import session
from app.dependencies import require_auth
from app.response.pinned_answers import (
    normalize_for_pin,
    validate_pin_package,
)

router = APIRouter()

VALID_AUDIENCES = ("staff", "client", "any")


class PinnedAnswerCreate(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    response_id: str = Field(min_length=1, max_length=100)
    audience: str = "staff"
    package: dict


class PinnedAnswerPatch(BaseModel):
    is_active: bool | None = None
    audience: str | None = None


def _row_to_dict(r: dict) -> dict:
    return {
        "id": r["id"],
        "query": r["query"],
        "audience": r["audience"],
        "confidence": r["confidence"],
        "source_response_id": r["source_response_id"],
        "is_active": r["is_active"],
        "created_at": str(r["created_at"]) if r["created_at"] else None,
        "updated_at": str(r["updated_at"]) if r["updated_at"] else None,
        "excerpt_count": len((r["package"] or {}).get("excerpts") or []),
    }


@router.get("/pinned-answers")
async def list_pinned_answers(
    user: dict = Depends(require_auth),
) -> dict:
    """List all pinned answers (admin only)."""
    require_role(user, "admin")
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, query, audience, package, confidence, "
                "source_response_id, is_active, created_at, updated_at "
                "FROM pinned_answers ORDER BY created_at DESC, id DESC"
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"pinned_answers": [_row_to_dict(r) for r in rows]}


@router.post("/pinned-answers", status_code=status.HTTP_201_CREATED)
async def create_pinned_answer(
    request: PinnedAnswerCreate,
    user: dict = Depends(require_auth),
) -> dict:
    """Pin a response package to an exact normalized query match.

    - ``response_id`` must reference a real entry in ``audit_log`` with a
      successful outcome — pins can only originate from actual searches.
    - The package must pass structural validation (routing 'answer' with
      verbatim excerpts/summary/facts).
    - Re-pinning the same normalized query replaces the stored package
      (upsert on ``query_norm``).
    """
    require_role(user, "admin")

    if request.audience not in VALID_AUDIENCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"audience must be one of {', '.join(VALID_AUDIENCES)}",
        )

    problems = validate_pin_package(request.package)
    if problems:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="; ".join(problems),
        )

    key = normalize_for_pin(request.query)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="query normalizes to empty",
        )

    with session.acquire() as conn:
        with conn.cursor() as cur:
            # The pin must trace back to a real, successful audited search.
            cur.execute(
                "SELECT outcome FROM audit_log WHERE response_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (request.response_id,),
            )
            audit_row = cur.fetchone()
            if audit_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="response_id not found in audit log",
                )
            if audit_row["outcome"] != "answer":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"source response outcome was '{audit_row['outcome']}' — "
                        "only fully answered responses can be pinned"
                    ),
                )

            confidence = request.package.get("confidence")
            cur.execute(
                "INSERT INTO pinned_answers "
                "(query, query_norm, audience, package, source_response_id, "
                "confidence, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (query_norm) DO UPDATE SET "
                "query = EXCLUDED.query, "
                "audience = EXCLUDED.audience, "
                "package = EXCLUDED.package, "
                "source_response_id = EXCLUDED.source_response_id, "
                "confidence = EXCLUDED.confidence, "
                "is_active = true, "
                "updated_at = now() "
                "RETURNING id, query, audience, package, confidence, "
                "source_response_id, is_active, created_at, updated_at",
                (
                    request.query.strip(),
                    key,
                    request.audience,
                    Json(request.package),
                    request.response_id,
                    float(confidence) if confidence is not None else 1.0,
                    int(user["id"]),
                ),
            )
            row = dict(cur.fetchone())
        conn.commit()

    return _row_to_dict(row)


@router.patch("/pinned-answers/{pin_id}")
async def patch_pinned_answer(
    pin_id: int,
    request: PinnedAnswerPatch,
    user: dict = Depends(require_auth),
) -> dict:
    """Toggle a pin active/inactive or change its audience."""
    require_role(user, "admin")

    if request.audience is not None and request.audience not in VALID_AUDIENCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"audience must be one of {', '.join(VALID_AUDIENCES)}",
        )
    if request.is_active is None and request.audience is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="nothing to update",
        )

    set_parts: list[str] = ["updated_at = now()"]
    params: list = []
    if request.is_active is not None:
        set_parts.append("is_active = %s")
        params.append(request.is_active)
    if request.audience is not None:
        set_parts.append("audience = %s")
        params.append(request.audience)
    params.append(pin_id)

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE pinned_answers SET {', '.join(set_parts)} "
                "WHERE id = %s RETURNING id",
                params,
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Pinned answer not found",
                )
        conn.commit()

    return {"message": "Pinned answer updated", "id": pin_id}


@router.delete("/pinned-answers/{pin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pinned_answer(
    pin_id: int,
    user: dict = Depends(require_auth),
) -> None:
    """Remove a pinned answer permanently."""
    require_role(user, "admin")
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pinned_answers WHERE id = %s", (pin_id,)
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Pinned answer not found",
                )
        conn.commit()
