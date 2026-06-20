from typing import Any

from minio import Minio
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.database import db_connection
from app.schemas import Game, GameInteractionState, GameManifest, GameVersionSummary, RemixResponse
from app.services.play_stats_service import pending_play_counts

_CATALOG_SCHEMA_READY = False


def ensure_catalog_runtime_schema() -> None:
    global _CATALOG_SCHEMA_READY
    if _CATALOG_SCHEMA_READY:
        return
    with db_connection() as connection:
        connection.execute(
            """
CREATE INDEX IF NOT EXISTS ix_play_events_user_daily
  ON play_events(game_id, user_id, event_type, created_at DESC)
  WHERE user_id IS NOT NULL
"""
        )
        connection.execute(
            """
CREATE INDEX IF NOT EXISTS ix_play_events_anonymous_daily
  ON play_events(game_id, anonymous_id, event_type, created_at DESC)
  WHERE anonymous_id IS NOT NULL
"""
        )
    _CATALOG_SCHEMA_READY = True


GAME_SELECT = """
SELECT
  g.id AS db_game_id,
  g.slug AS id,
  g.title,
  u.display_name AS author,
  g.description,
  COALESCE(array_agg(t.name ORDER BY t.name) FILTER (WHERE t.name IS NOT NULL), '{}') AS tags,
  g.published_at AS "publishedAt",
  cover.bucket AS cover_bucket,
  cover.object_key AS cover_object_key,
  cover.public_url AS cover_public_url,
  g.plays_count AS plays,
  g.likes_count AS likes,
  g.favorites_count AS favorites,
  CASE WHEN liked.user_id IS NULL THEN false ELSE true END AS "likedByMe",
  CASE WHEN favorited.user_id IS NULL THEN false ELSE true END AS "favoritedByMe",
  COALESCE(g.metadata ->> 'section', 'Recently Created') AS section
FROM games g
JOIN users u ON u.id = g.author_id
LEFT JOIN assets cover ON cover.id = g.cover_asset_id
LEFT JOIN game_tags gt ON gt.game_id = g.id
LEFT JOIN tags t ON t.id = gt.tag_id
LEFT JOIN game_likes liked ON liked.game_id = g.id AND liked.user_id = %s
LEFT JOIN game_favorites favorited ON favorited.game_id = g.id AND favorited.user_id = %s
WHERE
  g.publish_status = 'published'
  AND g.visibility = 'public'
  AND g.deleted_at IS NULL
"""


def _api_base_url() -> str:
    return f"http://localhost:{get_settings().api_port}"


def _cover_url_from_row(row: dict[str, Any]) -> str:
    if row.get("cover_bucket") == "external":
        return row.get("cover_public_url") or ""
    if row.get("cover_object_key"):
        return f"{_api_base_url()}/games/{row['id']}/cover"
    return row.get("cover_public_url") or ""


def _game_from_row(row: dict[str, Any], pending_plays: int = 0) -> Game:
    return Game(
        id=row["id"],
        title=row["title"],
        author=row["author"],
        description=row["description"],
        tags=list(row["tags"]),
        publishedAt=row["publishedAt"],
        coverUrl=_cover_url_from_row(row),
        plays=row["plays"] + pending_plays,
        likes=row["likes"],
        favorites=row["favorites"],
        likedByMe=row["likedByMe"],
        favoritedByMe=row["favoritedByMe"],
        section=row["section"],
    )


def _games_from_rows(rows: list[dict[str, Any]]) -> list[Game]:
    pending = pending_play_counts([str(row["db_game_id"]) for row in rows])
    return [_game_from_row(row, pending.get(str(row["db_game_id"]), 0)) for row in rows]


def _user_param(user_id: str | None) -> str | None:
    return user_id if user_id else None


def list_games(*, query: str | None = None, tag: str | None = None, user_id: str | None = None) -> list[Game]:
    params: list[Any] = [_user_param(user_id), _user_param(user_id)]
    where = ""
    cleaned_query = (query or "").strip()
    cleaned_tag = (tag or "").strip()
    if cleaned_query:
        where += """
  AND (
    g.title ILIKE %s
    OR g.description ILIKE %s
    OR EXISTS (
      SELECT 1
      FROM game_tags search_gt
      JOIN tags search_t ON search_t.id = search_gt.tag_id
      WHERE search_gt.game_id = g.id AND search_t.name ILIKE %s
    )
  )
"""
        like_query = f"%{cleaned_query}%"
        params.extend([like_query, like_query, like_query])
    if cleaned_tag:
        where += """
  AND EXISTS (
    SELECT 1
    FROM game_tags filter_gt
    JOIN tags filter_t ON filter_t.id = filter_gt.tag_id
    WHERE filter_gt.game_id = g.id AND lower(filter_t.name) = lower(%s)
  )
"""
        params.append(cleaned_tag)
    with db_connection() as connection:
        rows = connection.execute(
            GAME_SELECT
            + where
            + """
GROUP BY g.id, u.display_name, cover.bucket, cover.object_key, cover.public_url, liked.user_id, favorited.user_id
ORDER BY g.published_at DESC NULLS LAST, g.created_at DESC
""",
            params,
        ).fetchall()
    return _games_from_rows(rows)


def get_game(game_id: str, *, user_id: str | None = None) -> Game | None:
    with db_connection() as connection:
        row = connection.execute(
            GAME_SELECT
            + """
  AND g.slug = %s
GROUP BY g.id, u.display_name, cover.bucket, cover.object_key, cover.public_url, liked.user_id, favorited.user_id
LIMIT 1
""",
            (_user_param(user_id), _user_param(user_id), game_id),
        ).fetchone()
    return _games_from_rows([row])[0] if row else None


def list_tags() -> list[str]:
    with db_connection() as connection:
        rows = connection.execute(
            """
SELECT DISTINCT t.name
FROM tags t
JOIN game_tags gt ON gt.tag_id = t.id
JOIN games g ON g.id = gt.game_id
WHERE g.publish_status = 'published' AND g.visibility = 'public' AND g.deleted_at IS NULL
ORDER BY t.name
"""
        ).fetchall()
    return [row["name"] for row in rows]


def list_game_versions(game_slug: str) -> list[GameVersionSummary]:
    with db_connection() as connection:
        rows = connection.execute(
            """
SELECT
  gv.id,
  gv.version_no,
  gv.runtime,
  gv.build_status,
  gv.safety_status,
  gv.entry_file,
  gv.storage_prefix,
  gv.source_job_id,
  gv.created_at,
  manifest.public_url AS manifest_url
FROM games g
JOIN game_versions gv ON gv.game_id = g.id
LEFT JOIN assets manifest ON manifest.id = gv.manifest_asset_id
WHERE g.slug = %s AND g.deleted_at IS NULL
ORDER BY gv.version_no DESC
""",
            (game_slug,),
        ).fetchall()
    return [
        GameVersionSummary(
            versionId=str(row["id"]),
            versionNo=row["version_no"],
            runtime=row["runtime"],
            buildStatus=row["build_status"],
            safetyStatus=row["safety_status"],
            entryFile=row["entry_file"],
            storagePrefix=row["storage_prefix"],
            manifestUrl=row["manifest_url"],
            sourceJobId=str(row["source_job_id"]) if row["source_job_id"] else None,
            createdAt=row["created_at"],
        )
        for row in rows
    ]


def remix_game(game_slug: str, *, user_id: str) -> RemixResponse | None:
    with db_connection() as connection:
        source = connection.execute(
            """
SELECT
  g.id,
  g.slug,
  g.title,
  g.description,
  g.cover_asset_id,
  g.current_version_id,
  g.metadata,
  gv.runtime,
  gv.manifest_asset_id,
  gv.entry_file,
  gv.storage_prefix,
  gv.metadata AS version_metadata
FROM games g
LEFT JOIN game_versions gv ON gv.id = g.current_version_id
WHERE g.slug = %s AND g.publish_status = 'published' AND g.visibility = 'public' AND g.deleted_at IS NULL
LIMIT 1
""",
            (game_slug,),
        ).fetchone()
        if not source:
            return None
        remix_slug = f"remix-{source['slug']}-{str(user_id).replace('-', '')[:8]}"
        suffix = 1
        base_slug = remix_slug
        while connection.execute("SELECT 1 FROM games WHERE slug = %s", (remix_slug,)).fetchone():
            suffix += 1
            remix_slug = f"{base_slug}-{suffix}"
        remix_title = f"{source['title']} Remix"
        game = connection.execute(
            """
INSERT INTO games (
  slug, author_id, title, description, cover_asset_id, visibility, publish_status, metadata
)
VALUES (%s, %s, %s, %s, %s, 'private', 'draft', %s)
RETURNING id, slug, title, publish_status
""",
            (
                remix_slug,
                user_id,
                remix_title,
                source["description"],
                source["cover_asset_id"],
                Jsonb({
                    **(source["metadata"] or {}),
                    "remixOfGameId": str(source["id"]),
                    "remixOfSlug": source["slug"],
                    "section": "Recently Created",
                }),
            ),
        ).fetchone()
        version = connection.execute(
            """
INSERT INTO game_versions (
  game_id, version_no, runtime, manifest_asset_id, entry_file, build_status, safety_status, storage_prefix, metadata
)
VALUES (%s, 1, %s, %s, %s, 'succeeded', 'pending', %s, %s)
RETURNING id
""",
            (
                game["id"],
                source["runtime"] or "iframe-html5",
                source["manifest_asset_id"],
                source["entry_file"] or "index.html",
                f"remixes/{game['id']}/versions/1",
                Jsonb({
                    **(source["version_metadata"] or {}),
                    "remixOfVersionId": str(source["current_version_id"]) if source["current_version_id"] else None,
                }),
            ),
        ).fetchone()
        connection.execute("UPDATE games SET current_version_id = %s WHERE id = %s", (version["id"], game["id"]))
    return RemixResponse(
        gameId=str(game["id"]),
        gameSlug=game["slug"],
        projectId=None,
        title=game["title"],
        status=game["publish_status"],
    )


def _interaction_state(connection: Any, *, game_slug: str, user_id: str) -> GameInteractionState | None:
    row = connection.execute(
        """
SELECT
  g.slug,
  g.likes_count,
  g.favorites_count,
  EXISTS(SELECT 1 FROM game_likes gl WHERE gl.game_id = g.id AND gl.user_id = %s) AS liked,
  EXISTS(SELECT 1 FROM game_favorites gf WHERE gf.game_id = g.id AND gf.user_id = %s) AS favorited
FROM games g
WHERE g.slug = %s AND g.publish_status = 'published' AND g.visibility = 'public' AND g.deleted_at IS NULL
LIMIT 1
""",
        (user_id, user_id, game_slug),
    ).fetchone()
    if not row:
        return None
    return GameInteractionState(
        gameId=row["slug"],
        likes=row["likes_count"],
        favorites=row["favorites_count"],
        likedByMe=row["liked"],
        favoritedByMe=row["favorited"],
    )


def set_game_like(game_slug: str, *, user_id: str, liked: bool) -> GameInteractionState | None:
    with db_connection() as connection:
        game = connection.execute(
            """
SELECT id
FROM games
WHERE slug = %s AND publish_status = 'published' AND visibility = 'public' AND deleted_at IS NULL
LIMIT 1
""",
            (game_slug,),
        ).fetchone()
        if not game:
            return None
        if liked:
            inserted = connection.execute(
                """
INSERT INTO game_likes (user_id, game_id)
VALUES (%s, %s)
ON CONFLICT DO NOTHING
RETURNING user_id
""",
                (user_id, game["id"]),
            ).fetchone()
            if inserted:
                connection.execute("UPDATE games SET likes_count = likes_count + 1 WHERE id = %s", (game["id"],))
        else:
            deleted = connection.execute(
                """
DELETE FROM game_likes
WHERE user_id = %s AND game_id = %s
RETURNING user_id
""",
                (user_id, game["id"]),
            ).fetchone()
            if deleted:
                connection.execute("UPDATE games SET likes_count = GREATEST(likes_count - 1, 0) WHERE id = %s", (game["id"],))
        return _interaction_state(connection, game_slug=game_slug, user_id=user_id)


def set_game_favorite(game_slug: str, *, user_id: str, favorited: bool) -> GameInteractionState | None:
    with db_connection() as connection:
        game = connection.execute(
            """
SELECT id
FROM games
WHERE slug = %s AND publish_status = 'published' AND visibility = 'public' AND deleted_at IS NULL
LIMIT 1
""",
            (game_slug,),
        ).fetchone()
        if not game:
            return None
        if favorited:
            inserted = connection.execute(
                """
INSERT INTO game_favorites (user_id, game_id)
VALUES (%s, %s)
ON CONFLICT DO NOTHING
RETURNING user_id
""",
                (user_id, game["id"]),
            ).fetchone()
            if inserted:
                connection.execute("UPDATE games SET favorites_count = favorites_count + 1 WHERE id = %s", (game["id"],))
        else:
            deleted = connection.execute(
                """
DELETE FROM game_favorites
WHERE user_id = %s AND game_id = %s
RETURNING user_id
""",
                (user_id, game["id"]),
            ).fetchone()
            if deleted:
                connection.execute("UPDATE games SET favorites_count = GREATEST(favorites_count - 1, 0) WHERE id = %s", (game["id"],))
        return _interaction_state(connection, game_slug=game_slug, user_id=user_id)


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
SELECT kind, public_url
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
        assets=[
            f"{_api_base_url()}/games/{version['slug']}/cover" if row["kind"] == "cover" else row["public_url"]
            for row in asset_rows
        ],
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


def get_game_cover(game_id: str) -> tuple[bytes, str] | None:
    with db_connection() as connection:
        asset = connection.execute(
            """
SELECT cover.bucket, cover.object_key, cover.public_url, cover.content_type
FROM games g
JOIN assets cover ON cover.id = g.cover_asset_id
WHERE
  g.slug = %s
  AND g.publish_status = 'published'
  AND g.visibility = 'public'
  AND g.deleted_at IS NULL
LIMIT 1
""",
            (game_id,),
        ).fetchone()
    if not asset or asset["bucket"] == "external" or not asset["object_key"]:
        return None

    settings = get_settings()
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )
    response = client.get_object(asset["bucket"], asset["object_key"])
    try:
        content = response.read()
    finally:
        response.close()
        response.release_conn()
    return content, asset["content_type"] or "application/octet-stream"
