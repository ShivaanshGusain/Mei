"""web_search tool - search a known website for a query, via web_navigate."""

from typing import Dict, Any, Tuple, Optional
from urllib.parse import quote_plus

from ....core.config import ActionResult, VerifyResult
from ...context import ExecutionContext
from .navigate import web_navigate_execute, web_navigate_verify

# Search-URL formats are an external contract of each site, not something to
# discover dynamically — this list is deliberately small and just maps a site
# name to its query-string convention.
_SEARCH_TEMPLATES = {
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "google": "https://www.google.com/search?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/?q={query}",
    "amazon": "https://www.amazon.com/s?k={query}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={query}",
    "github": "https://github.com/search?q={query}",
}

WEB_SEARCH_SCHEMA = {
    "query": {"type": "str", "required": True, "description": "The search text"},
    "site": {"type": "str", "required": False, "default": "google",
             "description": "Which site to search: " + ", ".join(_SEARCH_TEMPLATES)},
}


def web_search_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    query = params.get("query")
    if not query or not str(query).strip():
        return False, "Missing or empty 'query' parameter"
    return True, None


def web_search_execute(params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
    query = str(params["query"]).strip()
    site = str(params.get("site", "google")).strip().lower()
    template = _SEARCH_TEMPLATES.get(site)

    if template is None:
        known = ", ".join(_SEARCH_TEMPLATES)
        return ActionResult(
            success=False,
            error=f"Unknown search site '{site}'. Known sites: {known}",
            method_used="web_search",
        )

    url = template.format(query=quote_plus(query))
    result = web_navigate_execute({"url": url, "new_tab": params.get("new_tab", False)}, context)
    context.set_variable("last_search_site", site)
    context.set_variable("last_search_query", query)
    return result


def web_search_verify(params: Dict[str, Any], context: ExecutionContext, result: ActionResult) -> VerifyResult:
    site = str(params.get("site", "google")).strip().lower()
    template = _SEARCH_TEMPLATES.get(site, _SEARCH_TEMPLATES["google"])
    fake_url = template.split("?")[0]
    return web_navigate_verify({"url": fake_url}, context, result)
