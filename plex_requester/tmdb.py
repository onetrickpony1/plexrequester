"""TMDb lookup and Plex-friendly media naming."""

from http import HTTPStatus
from urllib import error, parse, request
import json
import re


def tmdb_api_key(config):
    return str(config.get("tmdb", {}).get("apiKey", "")).strip()


def split_tmdb_query(query):
    years = re.findall(r"\b(?:19|20)\d{2}\b", query)
    without_year = re.sub(r"\b(?:19|20)\d{2}\b", " ", query)
    title = re.sub(r"\s+", " ", without_year).strip()
    if years and title:
        return title, years[-1]
    return str(query or "").strip(), None


def clean_folder_name(value):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(value or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "Untitled"


def tmdb_folder_name(title, year, season=None):
    base = clean_folder_name(title)
    if year:
        base = f"{base} ({year})"
    if season is not None:
        base = f"{base} S{int(season):02d}"
    return base


def tmdb_request(config, endpoint, params):
    api_key = tmdb_api_key(config)
    if not api_key:
        raise RuntimeError("Save a TMDb API key in the Plex Requester log window first.")

    query_params = {
        "language": "en-US",
        "include_adult": "false",
        **params,
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": "PlexRequester/1.0",
    }

    key = api_key.removeprefix("Bearer ").strip()
    if api_key.startswith("Bearer ") or "." in key or len(key) > 40:
        headers["Authorization"] = f"Bearer {key}"
    else:
        query_params["api_key"] = key

    url = "https://api.themoviedb.org/3" + endpoint + "?" + parse.urlencode(query_params)
    req = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("status_message") or detail
        except json.JSONDecodeError:
            message = detail or exc.reason
        if exc.code == HTTPStatus.UNAUTHORIZED:
            raise RuntimeError("TMDb rejected the saved API key.") from exc
        raise RuntimeError(f"TMDb returned HTTP {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Could not reach TMDb: {exc.reason}") from exc


def normalize_tmdb_item(item, media_type):
    if media_type == "movie":
        title = item.get("title") or item.get("original_title") or "Untitled"
        date = item.get("release_date") or ""
    else:
        title = item.get("name") or item.get("original_name") or "Untitled"
        date = item.get("first_air_date") or ""
    year = date[:4] if re.match(r"^\d{4}", date) else ""
    folder = tmdb_folder_name(title, year)
    return {
        "id": item.get("id"),
        "type": media_type,
        "title": title,
        "year": year,
        "date": date,
        "overview": item.get("overview") or "",
        "posterPath": item.get("poster_path") or "",
        "popularity": item.get("popularity") or 0,
        "voteAverage": item.get("vote_average") or 0,
        "folderName": folder,
        "seasonFolderName": tmdb_folder_name(title, year, 1) if media_type == "tv" else "",
    }


def search_tmdb(config, query, media_type):
    query = str(query or "").strip()
    if len(query) < 2:
        return {"configured": bool(tmdb_api_key(config)), "items": []}

    title, year = split_tmdb_query(query)
    if not title:
        title = query
    search_types = ["movie", "tv"] if media_type == "all" else [media_type]
    items = []

    for search_type in search_types:
        endpoint = "/search/movie" if search_type == "movie" else "/search/tv"
        params = {"query": title, "page": "1"}
        if year:
            params["primary_release_year" if search_type == "movie" else "first_air_date_year"] = year
        response = tmdb_request(config, endpoint, params)
        for item in response.get("results", [])[:8]:
            items.append(normalize_tmdb_item(item, search_type))

    items.sort(key=lambda item: item.get("popularity", 0), reverse=True)
    return {"configured": True, "items": items[:12]}



