"""Plex database snapshots, search, media analysis, and fulfillment matching."""

from pathlib import Path
from urllib import parse
import difflib
import re
import shutil
import sqlite3
import tempfile
import threading
import time

from .requests import quality_satisfies_request, request_quality


PLEX_ANALYSIS_CACHE_LOCK = threading.RLock()
PLEX_ANALYSIS_CACHE = {}
PLEX_ANALYSIS_CACHE_SECONDS = 60


def int_value(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def media_resolution_height(item):
    height = int_value(item.get("height"))
    if height:
        return height

    resolution = str(item.get("video_resolution") or item.get("display_aspect_ratio") or "").lower()
    match = re.search(r"(\d{3,4})", resolution)
    return int(match.group(1)) if match else 0


def stream_bitrate_kbps(value):
    """Convert Plex media_streams.bitrate bits/second values to kbps."""
    bits_per_second = int_value(value)
    return round(bits_per_second / 1000) if bits_per_second else 0


def media_bitrate(item, stream_rows):
    bitrate = int_value(item.get("bitrate"))
    media_id = item.get("id")
    for stream in stream_rows:
        if str(stream.get("media_item_id")) == str(media_id):
            bitrate = max(bitrate, stream_bitrate_kbps(stream.get("bitrate")))
    return bitrate


def video_stream_for_media(item, stream_rows):
    media_id = item.get("id")
    candidates = [
        stream for stream in stream_rows
        if str(stream.get("media_item_id")) == str(media_id)
    ]
    video_candidates = [
        stream for stream in candidates
        if str(stream.get("stream_type", stream.get("stream_type_id", ""))).lower() in {"1", "video"}
    ]
    return video_candidates[0] if video_candidates else {}


def media_analysis_complete(media_items, stream_rows):
    if not media_items:
        return False

    for item in media_items:
        stream = video_stream_for_media(item, stream_rows)
        codec = stream.get("codec") or item.get("video_codec") or item.get("codec")
        if not media_bitrate(item, stream_rows):
            return False
        if not (media_resolution_height(item) or int_value(item.get("width"))):
            return False
        if not codec:
            return False
    return True


def classify_media_quality(media_items, stream_rows):
    qualities = set()
    for item in media_items:
        height = media_resolution_height(item)
        width = int_value(item.get("width"))
        bitrate = media_bitrate(item, stream_rows)

        if bitrate >= 30000:
            qualities.add("REMUX")
        if height >= 2000 or width >= 3800:
            qualities.add("4K")
        elif height >= 1000 or width >= 1800:
            qualities.add("1080p")
    return qualities


def bitrate_label(value):
    bitrate = int_value(value)
    if not bitrate:
        return ""
    return f"{round(bitrate / 1000, 1):g} Mbps"


def average_episode_bitrate(media_items, stream_rows):
    episode_bitrates = {}
    for item in media_items:
        episode_id = str(item.get("metadata_item_id") or item.get("id") or "")
        bitrate = media_bitrate(item, stream_rows)
        if episode_id and bitrate:
            episode_bitrates[episode_id] = max(episode_bitrates.get(episode_id, 0), bitrate)
    values = list(episode_bitrates.values())
    return round(sum(values) / len(values)) if values else 0


def media_quality_summary(media_items, stream_rows, average_bitrate=False):
    if not media_items:
        return ""

    best = max(
        media_items,
        key=lambda item: (
            media_bitrate(item, stream_rows),
            int_value(item.get("width")),
            int_value(item.get("height")),
        ),
    )
    stream = video_stream_for_media(best, stream_rows)
    parts = []
    height = media_resolution_height(best)
    width = int_value(best.get("width"))
    bitrate = average_episode_bitrate(media_items, stream_rows) if average_bitrate else media_bitrate(best, stream_rows)
    codec = stream.get("codec") or best.get("video_codec") or best.get("codec")

    if media_bitrate(best, stream_rows) >= 30000:
        parts.append("REMUX")
    elif height >= 2000 or width >= 3800:
        parts.append("4K")
    elif height >= 1000 or width >= 1800:
        parts.append("1080p")

    label = bitrate_label(bitrate)
    if label:
        parts.append(f"{label} average" if average_bitrate else label)
    if codec:
        parts.append(str(codec).upper())
    return " - ".join(parts)


def media_rows_for_library_item_connection(connection, item):
    item_id = item.get("id")

    if item.get("type") == "show":
        media_rows = connection.execute(
            """
            SELECT media.*
            FROM metadata_items season
            JOIN metadata_items episode ON episode.parent_id = season.id
            JOIN media_items media ON media.metadata_item_id = episode.id
            WHERE season.parent_id = ?
              AND season.metadata_type = 3
              AND episode.metadata_type = 4
              AND season.deleted_at IS NULL
              AND episode.deleted_at IS NULL
            """,
            (item_id,),
        ).fetchall()
    else:
        media_rows = connection.execute(
            "SELECT * FROM media_items WHERE metadata_item_id = ?",
            (item_id,),
        ).fetchall()

    media_items = sqlite_rows_to_dicts(media_rows)
    media_ids = [row.get("id") for row in media_items if row.get("id") is not None]
    stream_rows = []
    if media_ids and sqlite_table_exists(connection, "media_streams"):
        columns = sqlite_table_columns(connection, "media_streams")
        if "media_item_id" in columns:
            placeholders = ",".join("?" for _ in media_ids)
            stream_rows = sqlite_rows_to_dicts(
                connection.execute(
                    f"SELECT * FROM media_streams WHERE media_item_id IN ({placeholders})",
                    media_ids,
                ).fetchall()
            )
    return media_items, stream_rows


def media_rows_for_library_item(database_path, item):
    if not database_path or not database_path.exists():
        return [], []

    snapshot_path = snapshot_plex_database(database_path)
    connection = None
    try:
        connection = sqlite3.connect(snapshot_path)
        connection.row_factory = sqlite3.Row
        return media_rows_for_library_item_connection(connection, item)
    finally:
        try:
            connection.close()
        except Exception:
            pass
        try:
            snapshot_path.unlink(missing_ok=True)
        except OSError:
            pass


def quality_warning(requested_quality, qualities, match_title="", match_year="", quality_summary=""):
    matched = f"{match_title} ({match_year})" if match_title and match_year else match_title
    detail = quality_summary or ", ".join(sorted(qualities, key=lambda value: ["1080p", "4K", "REMUX"].index(value)))
    if quality_satisfies_request(requested_quality, qualities):
        suffix = f": {detail}" if detail else f" as {requested_quality}"
        return f"Found in Plex{f' - {matched}' if matched else ''}{suffix}. Please check first."
    if qualities:
        return f"Title appears to be in Plex, but at a different quality: {detail}."
    return "Already appears to be in Plex, but quality could not be confirmed. Please check first."


def strict_plex_matches(items, tmdb_title, tmdb_year):
    wanted_title = normalize_search_text(tmdb_title)
    wanted_year = str(tmdb_year or "").strip()
    matches = []

    for item in items:
        item_title = normalize_search_text(item.get("title", ""))
        item_year = str(item.get("year") or "").strip()
        if item_title != wanted_title:
            continue
        if wanted_year and item_year and item_year != wanted_year:
            continue
        matches.append(item)

    return matches


def plex_match_for_tmdb(config, tmdb_item):
    if not isinstance(tmdb_item, dict):
        return None

    title = str(tmdb_item.get("title", "")).strip()
    year = tmdb_item.get("year")
    media_type = "show" if tmdb_item.get("type") == "tv" else "movie"
    if not title:
        return None

    query = f"{title} {year}" if year else title
    try:
        result = search_plex_database(plex_database_path(config), query, media_type, limit=5)
    except (OSError, sqlite3.DatabaseError):
        return None

    items = result.get("items", [])
    items = strict_plex_matches(items, title, year)
    if not items:
        return None
    return items[0]


def plex_analysis_cache_key(config, tmdb_item):
    database_path = plex_database_path(config)
    database_fingerprint = []
    if database_path:
        for path in (database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm")):
            try:
                stat = path.stat()
                database_fingerprint.append((stat.st_mtime_ns, stat.st_size))
            except OSError:
                database_fingerprint.append((0, 0))
    return (
        str(database_path or ""),
        tuple(database_fingerprint),
        str(tmdb_item.get("type") or ""),
        str(tmdb_item.get("id") or ""),
        normalize_search_text(tmdb_item.get("title") or ""),
        str(tmdb_item.get("year") or ""),
    )


def plex_analysis_for_tmdb(config, tmdb_item, match_provider=None, media_rows_provider=None):
    match_provider = match_provider or plex_match_for_tmdb
    media_rows_provider = media_rows_provider or media_rows_for_library_item
    if not isinstance(tmdb_item, dict):
        return {"match": None, "qualities": set(), "summary": "", "analyzed": False}
    cache_key = plex_analysis_cache_key(config, tmdb_item)
    now = time.monotonic()
    with PLEX_ANALYSIS_CACHE_LOCK:
        cached = PLEX_ANALYSIS_CACHE.get(cache_key)
        if cached and now - cached["createdAt"] < PLEX_ANALYSIS_CACHE_SECONDS:
            return cached["analysis"]

    match = match_provider(config, tmdb_item)
    qualities = set()
    summary = ""
    analyzed = False
    if match:
        try:
            media_items, stream_rows = media_rows_provider(plex_database_path(config), match)
            analyzed = media_analysis_complete(media_items, stream_rows)
            if analyzed:
                qualities = classify_media_quality(media_items, stream_rows)
                summary = media_quality_summary(
                    media_items,
                    stream_rows,
                    average_bitrate=match.get("type") == "show",
                )
        except (OSError, sqlite3.DatabaseError):
            pass
    analysis = {"match": match, "qualities": qualities, "summary": summary, "analyzed": analyzed}
    with PLEX_ANALYSIS_CACHE_LOCK:
        for key, entry in list(PLEX_ANALYSIS_CACHE.items()):
            if now - entry["createdAt"] >= PLEX_ANALYSIS_CACHE_SECONDS:
                PLEX_ANALYSIS_CACHE.pop(key, None)
        PLEX_ANALYSIS_CACHE[cache_key] = {"createdAt": now, "analysis": analysis}
    return analysis


def library_warning_for_request(config, tmdb_item, requested_quality, analysis_provider=None):
    analysis_provider = analysis_provider or plex_analysis_for_tmdb
    analysis = analysis_provider(config, tmdb_item)
    match = analysis["match"]
    if not match:
        return ""

    return quality_warning(
        requested_quality,
        analysis["qualities"],
        match.get("title", ""),
        match.get("year", ""),
        analysis["summary"],
    )


def current_request_plex_status(config, item, analysis_provider=None):
    analysis_provider = analysis_provider or plex_analysis_for_tmdb
    tmdb_item = item.get("tmdb")
    if not isinstance(tmdb_item, dict):
        return None

    requested_quality = request_quality(item.get("quality"))
    analysis = analysis_provider(config, tmdb_item)
    match = analysis["match"]
    if not match:
        return {
            "state": "open",
            "message": "Not in Plex yet.",
        }

    if not analysis.get("analyzed"):
        return {
            "state": "open",
            "message": "In Plex; waiting for Plex media analysis.",
        }

    qualities = analysis["qualities"]
    summary = analysis["summary"]

    if quality_satisfies_request(requested_quality, qualities):
        return {
            "state": "fulfilled",
            "message": f"Fulfilled: {summary or requested_quality}.",
        }
    if qualities:
        return {
            "state": "partial",
            "message": f"In Plex at different quality: {summary or ', '.join(sorted(qualities))}.",
        }
    return {
        "state": "open",
        "message": "In Plex; waiting for complete quality details.",
    }


def plex_database_path(config):
    value = str(config.get("plex", {}).get("databasePath", "")).strip()
    if not value:
        return None
    return Path(value)


def snapshot_plex_database(database_path):
    source_uri = "file:" + parse.quote(str(database_path.resolve()).replace("\\", "/"), safe="/:") + "?mode=ro"
    temp = tempfile.NamedTemporaryFile(prefix="plex-requester-", suffix=".db", delete=False)
    temp_path = Path(temp.name)
    temp.close()

    source = None
    target = None
    try:
        source = sqlite3.connect(source_uri, uri=True)
        target = sqlite3.connect(temp_path)
        source.backup(target)
        target.close()
        source.close()
        return temp_path
    except Exception:
        if target:
            target.close()
        if source:
            source.close()
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def normalize_search_text(value):
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_library_query(query):
    years = re.findall(r"\b(?:19|20)\d{2}\b", query)
    title_without_years = re.sub(r"\b(?:19|20)\d{2}\b", " ", query)
    normalized_without_years = normalize_search_text(title_without_years)
    if years and normalized_without_years:
        return normalized_without_years, set(years)
    return normalize_search_text(query), set()


def library_match_score(row, query_title, query_years):
    title = normalize_search_text(row["title"])
    if not query_title and not query_years:
        return 1.0

    score = 0.0
    if query_title:
        ratio = difflib.SequenceMatcher(None, query_title, title).ratio()
        query_tokens = set(query_title.split())
        title_tokens = set(title.split())
        token_score = len(query_tokens & title_tokens) / max(len(query_tokens), 1)

        shorter = min(len(query_title), len(title))
        if query_title == title:
            score += 1.0
        elif shorter >= 3 and (query_title in title or title in query_title):
            score += 0.82
        else:
            score += max(ratio * 0.72, token_score * 0.78)

    if query_years:
        year = str(row["year"] or "")
        if year in query_years:
            score += 0.35
        else:
            score -= 0.2

    return score


def library_match_threshold(query_title, query_years):
    if not query_title and not query_years:
        return 0.0
    token_count = len(query_title.split()) if query_title else 0
    if token_count <= 1:
        return 0.48
    return 0.62


def library_match_label(row, query_title, score):
    if not query_title:
        return ""
    title = normalize_search_text(row["title"])
    return "Exact" if title == query_title else "Similar"


def row_to_library_item(row, match_label="", quality_summary=""):
    return {
        "id": row["id"],
        "title": row["title"],
        "year": row["year"],
        "type": "movie" if row["metadata_type"] == 1 else "show",
        "library": row["library_name"],
        "originallyAvailableAt": row["originally_available_at"],
        "episodeCount": row["episode_count"],
        "fileCount": row["file_count"],
        "sampleFile": row["sample_file"],
        "match": match_label,
        "qualitySummary": quality_summary,
    }


def sqlite_rows_to_dicts(rows):
    return [{key: row[key] for key in row.keys()} for row in rows]


def sqlite_table_columns(connection, table_name):
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()]


def sqlite_table_exists(connection, table_name):
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def fetch_optional_rows(connection, table_name, where_sql, params):
    if not sqlite_table_exists(connection, table_name):
        return []
    return sqlite_rows_to_dicts(connection.execute(f"SELECT * FROM {table_name} WHERE {where_sql}", params).fetchall())


def search_plex_database(database_path, query="", media_type="all", limit=80):
    if not database_path or not database_path.exists():
        return {
            "configured": bool(database_path),
            "items": [],
            "error": "Plex database path is not configured or does not exist.",
        }

    snapshot_path = snapshot_plex_database(database_path)
    try:
        connection = sqlite3.connect(snapshot_path)
        connection.row_factory = sqlite3.Row
        params = []
        filters = ["mi.metadata_type IN (1, 2)", "mi.deleted_at IS NULL"]

        if media_type == "movie":
            filters.append("mi.metadata_type = 1")
        elif media_type == "show":
            filters.append("mi.metadata_type = 2")

        sql = f"""
            SELECT
                mi.id,
                mi.title,
                mi.year,
                mi.originally_available_at,
                mi.metadata_type,
                ls.name AS library_name,
                COUNT(DISTINCT ep.id) AS episode_count,
                COUNT(DISTINCT parts.id) AS file_count,
                MIN(parts.file) AS sample_file
            FROM metadata_items mi
            LEFT JOIN library_sections ls ON ls.id = mi.library_section_id
            LEFT JOIN metadata_items season
                ON mi.metadata_type = 2
                AND season.parent_id = mi.id
                AND season.metadata_type = 3
                AND season.deleted_at IS NULL
            LEFT JOIN metadata_items ep
                ON mi.metadata_type = 2
                AND ep.parent_id = season.id
                AND ep.metadata_type = 4
                AND ep.deleted_at IS NULL
            LEFT JOIN media_items media ON media.metadata_item_id = mi.id
            LEFT JOIN media_parts parts ON parts.media_item_id = media.id
            WHERE {" AND ".join(filters)}
            GROUP BY mi.id
            ORDER BY lower(mi.title), mi.year
        """

        rows = connection.execute(sql, params).fetchall()
        query_title, query_years = parse_library_query(query)
        match_labels = {}
        if query_title or query_years:
            scored_rows = [
                (library_match_score(row, query_title, query_years), row)
                for row in rows
            ]
            threshold = library_match_threshold(query_title, query_years)
            scored_rows = [(score, row) for score, row in scored_rows if score >= threshold]
            scored_rows.sort(
                key=lambda item: (
                    library_match_label(item[1], query_title, item[0]) != "Exact",
                    -item[0],
                    normalize_search_text(item[1]["title"]),
                    item[1]["year"] or 0,
                )
            )
            match_labels = {
                row["id"]: library_match_label(row, query_title, score)
                for score, row in scored_rows
            }
            rows = [row for _, row in scored_rows[: int(limit)]]
        else:
            rows = rows[: int(limit)]

        quality_summaries = {}
        for row in rows:
            item = {
                "id": row["id"],
                "type": "movie" if row["metadata_type"] == 1 else "show",
            }
            try:
                media_items, stream_rows = media_rows_for_library_item_connection(connection, item)
                quality_summaries[row["id"]] = media_quality_summary(media_items, stream_rows)
            except sqlite3.DatabaseError:
                quality_summaries[row["id"]] = ""

        return {
            "configured": True,
            "items": [
                row_to_library_item(
                    row,
                    match_labels.get(row["id"], ""),
                    quality_summaries.get(row["id"], ""),
                )
                for row in rows
            ],
        }
    finally:
        try:
            connection.close()
        except Exception:
            pass
        try:
            snapshot_path.unlink(missing_ok=True)
        except OSError:
            pass


def plex_item_details(database_path, item_id):
    if not database_path or not database_path.exists():
        return {
            "configured": bool(database_path),
            "error": "Plex database path is not configured or does not exist.",
        }

    snapshot_path = snapshot_plex_database(database_path)
    try:
        connection = sqlite3.connect(snapshot_path)
        connection.row_factory = sqlite3.Row

        item = connection.execute("SELECT * FROM metadata_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return {"configured": True, "error": "Plex item was not found."}

        item_dict = {key: item[key] for key in item.keys()}
        details = {
            "configured": True,
            "metadata": item_dict,
            "librarySection": None,
            "parents": [],
            "children": [],
            "mediaItems": [],
            "mediaParts": [],
            "tags": [],
            "relatedTables": {},
        }

        library_section_id = item_dict.get("library_section_id")
        if library_section_id is not None and sqlite_table_exists(connection, "library_sections"):
            row = connection.execute("SELECT * FROM library_sections WHERE id = ?", (library_section_id,)).fetchone()
            if row:
                details["librarySection"] = {key: row[key] for key in row.keys()}

        parent_id = item_dict.get("parent_id")
        while parent_id:
            parent = connection.execute("SELECT * FROM metadata_items WHERE id = ?", (parent_id,)).fetchone()
            if not parent:
                break
            parent_dict = {key: parent[key] for key in parent.keys()}
            details["parents"].append(parent_dict)
            parent_id = parent_dict.get("parent_id")

        direct_children = connection.execute(
            "SELECT * FROM metadata_items WHERE parent_id = ? AND deleted_at IS NULL ORDER BY metadata_type, \"index\", title",
            (item_id,),
        ).fetchall()
        details["children"] = sqlite_rows_to_dicts(direct_children)

        if item_dict.get("metadata_type") == 2:
            episode_rows = connection.execute(
                """
                SELECT ep.*
                FROM metadata_items season
                JOIN metadata_items ep ON ep.parent_id = season.id
                WHERE season.parent_id = ?
                  AND season.metadata_type = 3
                  AND ep.metadata_type = 4
                  AND season.deleted_at IS NULL
                  AND ep.deleted_at IS NULL
                ORDER BY season."index", ep."index", ep.title
                """,
                (item_id,),
            ).fetchall()
            details["episodes"] = sqlite_rows_to_dicts(episode_rows)

        details["mediaItems"] = fetch_optional_rows(connection, "media_items", "metadata_item_id = ?", (item_id,))
        media_item_ids = [row["id"] for row in details["mediaItems"] if "id" in row]
        if media_item_ids and sqlite_table_exists(connection, "media_parts"):
            placeholders = ",".join("?" for _ in media_item_ids)
            details["mediaParts"] = sqlite_rows_to_dicts(
                connection.execute(
                    f"SELECT * FROM media_parts WHERE media_item_id IN ({placeholders})",
                    media_item_ids,
                ).fetchall()
            )

        if sqlite_table_exists(connection, "taggings"):
            taggings_columns = sqlite_table_columns(connection, "taggings")
            metadata_column = "metadata_item_id" if "metadata_item_id" in taggings_columns else None
            if metadata_column:
                taggings = fetch_optional_rows(connection, "taggings", f"{metadata_column} = ?", (item_id,))
                details["relatedTables"]["taggings"] = taggings
                tag_ids = [row.get("tag_id") for row in taggings if row.get("tag_id") is not None]
                if tag_ids and sqlite_table_exists(connection, "tags"):
                    placeholders = ",".join("?" for _ in tag_ids)
                    details["tags"] = sqlite_rows_to_dicts(
                        connection.execute(f"SELECT * FROM tags WHERE id IN ({placeholders})", tag_ids).fetchall()
                    )

        for table_name in ("metadata_item_settings", "statistics_media", "media_streams"):
            if not sqlite_table_exists(connection, table_name):
                continue
            columns = sqlite_table_columns(connection, table_name)
            if "metadata_item_id" in columns:
                details["relatedTables"][table_name] = fetch_optional_rows(
                    connection,
                    table_name,
                    "metadata_item_id = ?",
                    (item_id,),
                )
            elif table_name == "media_streams" and media_item_ids and "media_item_id" in columns:
                placeholders = ",".join("?" for _ in media_item_ids)
                details["relatedTables"][table_name] = sqlite_rows_to_dicts(
                    connection.execute(
                        f"SELECT * FROM media_streams WHERE media_item_id IN ({placeholders})",
                        media_item_ids,
                    ).fetchall()
                )

        return details
    finally:
        try:
            connection.close()
        except Exception:
            pass
        try:
            snapshot_path.unlink(missing_ok=True)
        except OSError:
            pass

