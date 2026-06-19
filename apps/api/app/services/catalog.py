from typing import Any

from minio import Minio

from app.config import get_settings
from app.database import db_connection
from app.schemas import Game, GameManifest


GAME_SELECT = """
SELECT
  g.slug AS id,
  g.title,
  u.display_name AS author,
  g.description,
  COALESCE(array_agg(t.name ORDER BY t.name) FILTER (WHERE t.name IS NOT NULL), '{}') AS tags,
  g.published_at AS "publishedAt",
  COALESCE(cover.public_url, '') AS "coverUrl",
  g.plays_count AS plays,
  COALESCE(g.metadata ->> 'section', 'Recently Created') AS section
FROM games g
JOIN users u ON u.id = g.author_id
LEFT JOIN assets cover ON cover.id = g.cover_asset_id
LEFT JOIN game_tags gt ON gt.game_id = g.id
LEFT JOIN tags t ON t.id = gt.tag_id
WHERE
  g.publish_status = 'published'
  AND g.visibility = 'public'
  AND g.deleted_at IS NULL
"""


def _game_from_row(row: dict[str, Any]) -> Game:
    return Game(
        id=row["id"],
        title=row["title"],
        author=row["author"],
        description=row["description"],
        tags=list(row["tags"]),
        publishedAt=row["publishedAt"],
        coverUrl=row["coverUrl"],
        plays=row["plays"],
        section=row["section"],
    )


def list_games() -> list[Game]:
    with db_connection() as connection:
        rows = connection.execute(
            GAME_SELECT
            + """
GROUP BY g.id, u.display_name, cover.public_url
ORDER BY g.published_at DESC NULLS LAST, g.created_at DESC
"""
        ).fetchall()
    return [_game_from_row(row) for row in rows]


def get_game(game_id: str) -> Game | None:
    with db_connection() as connection:
        row = connection.execute(
            GAME_SELECT
            + """
  AND g.slug = %s
GROUP BY g.id, u.display_name, cover.public_url
LIMIT 1
""",
            (game_id,),
        ).fetchone()
    return _game_from_row(row) if row else None


def get_game_manifest(game_id: str) -> GameManifest | None:
    with db_connection() as connection:
        version = connection.execute(
            """
SELECT
  g.id AS db_game_id,
  g.slug,
  g.title,
  gv.id AS version_id,
  gv.version_no,
  gv.runtime,
  gv.entry_file,
  manifest.public_url AS manifest_url,
  bundle.public_url AS bundle_url
FROM games g
JOIN game_versions gv ON gv.id = g.current_version_id
LEFT JOIN assets manifest ON manifest.id = gv.manifest_asset_id
LEFT JOIN LATERAL (
  SELECT a.public_url
  FROM assets a
  WHERE
    a.version_id = gv.id
    AND a.kind = 'bundle'
    AND a.public_url IS NOT NULL
  ORDER BY a.created_at DESC
  LIMIT 1
) bundle ON true
WHERE
  g.slug = %s
  AND g.publish_status = 'published'
  AND g.visibility = 'public'
  AND g.deleted_at IS NULL
LIMIT 1
""",
            (game_id,),
        ).fetchone()
        if not version:
            return None

        asset_rows = connection.execute(
            """
SELECT public_url
FROM assets
WHERE
  (game_id = %s OR version_id = %s)
  AND public_url IS NOT NULL
ORDER BY
  CASE kind
    WHEN 'cover' THEN 1
    WHEN 'manifest' THEN 2
    WHEN 'bundle' THEN 3
    ELSE 4
  END,
  created_at
""",
            (version["db_game_id"], version["version_id"]),
        ).fetchall()

    return GameManifest(
        id=version["slug"],
        title=version["title"],
        version=str(version["version_no"]),
        entry=version["entry_file"],
        bundleUrl=version["bundle_url"] or version["manifest_url"] or "",
        documentUrl=version["bundle_url"] or version["manifest_url"] or "",
        assets=[row["public_url"] for row in asset_rows],
        runtime=version["runtime"],
    )


def get_game_document(game_id: str) -> str | None:
    with db_connection() as connection:
        asset = connection.execute(
            """
SELECT bundle.bucket, bundle.object_key
FROM games g
JOIN game_versions gv ON gv.id = g.current_version_id
JOIN assets bundle ON bundle.version_id = gv.id AND bundle.kind = 'bundle'
WHERE
  g.slug = %s
  AND g.publish_status = 'published'
  AND g.visibility = 'public'
  AND g.deleted_at IS NULL
ORDER BY bundle.created_at DESC
LIMIT 1
""",
            (game_id,),
        ).fetchone()
    if not asset:
        return None

    settings = get_settings()
    if asset["bucket"] == "external":
        return None
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )
    response = client.get_object(asset["bucket"], asset["object_key"])
    try:
        return response.read().decode("utf-8")
    finally:
        response.close()
        response.release_conn()
