"""Flask web app for 1C Help viewer."""

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from ._utils import mask_path_for_log, safe_error_message
from .tree import build_tree_for_web, get_html_content


def _allowed_base_dirs():
    """If HELP_SERVE_ALLOWED_DIRS is set (comma-separated), return list of resolved paths; else empty (no restriction)."""
    raw = os.environ.get("HELP_SERVE_ALLOWED_DIRS", "").strip()
    if not raw:
        return []
    return [Path(p.strip()).resolve() for p in raw.split(",") if p.strip()]


def _directory_allowed(directory: str) -> bool:
    """Allow directory only if HELP_SERVE_ALLOWED_DIRS is set and directory is in the list.
    When allowlist is empty, reject any user-provided path (security: prevents arbitrary fs access)."""
    allowed = _allowed_base_dirs()
    if not allowed:
        return False
    try:
        resolved = Path(directory).resolve()
        return any(resolved == d or resolved.is_relative_to(d) for d in allowed)
    except (ValueError, OSError):
        return False


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder=Path(__file__).resolve().parent.parent.parent / "templates")
app.config["BASE_DIR"] = None


@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


@app.route("/", methods=["GET", "POST"])
def index():
    """Handle main page. When BASE_DIR set from config, show tree directly (no form)."""
    import json

    base_dir = app.config.get("BASE_DIR")
    if request.method == "POST" and not base_dir:
        directory = request.form.get("directory")
        if not directory or not Path(directory).is_dir():
            return render_template("index.html", error="Invalid directory path")
        if not _directory_allowed(directory):
            allowed = _allowed_base_dirs()
            err = (
                "HELP_SERVE_ALLOWED_DIRS must be set (comma-separated paths) to restrict serve."
                if not allowed
                else "Directory not in allowed list (HELP_SERVE_ALLOWED_DIRS)"
            )
            return render_template("index.html", error=err)
        app.config["BASE_DIR"] = directory
        base_dir = directory

    if base_dir and Path(base_dir).is_dir():
        tree_elements = build_tree_for_web(base_dir)
        return render_template(
            "index.html",
            success=True,
            tree_elements=json.dumps(tree_elements),
            from_config=bool(base_dir),
        )
    return render_template("index.html", success=False, tree_elements="[]")


@app.route("/content/<path:html_path>")
def get_content(html_path: str):
    """Serve HTML content for a given path."""
    try:
        base_dir = app.config["BASE_DIR"]
        if not base_dir:
            return jsonify({"error": "No directory selected"}), 400
        content = get_html_content(html_path, base_dir)
        return jsonify({"content": content})
    except Exception as e:
        logger.error(
            "Error serving content for %s: %s", mask_path_for_log(html_path), type(e).__name__
        )
        return jsonify({"error": safe_error_message(e)}), 500


@app.route("/download/<path:file_path>")
def download_file(file_path: str):
    """Download a file from the base directory."""
    base_dir = app.config["BASE_DIR"]
    if not base_dir:
        return jsonify({"error": "No directory selected"}), 400
    return send_from_directory(base_dir, file_path)


@app.route("/api/search")
def api_search():
    """Search 1C help via Qdrant (semantic + keyword hybrid)."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": [], "error": None})
    try:
        from .indexer import search_hybrid

        results = search_hybrid(q, limit=20)
        return jsonify({"results": results, "error": None})
    except Exception as e:
        logger.exception("Search failed: %s", e)
        return jsonify({"results": [], "error": safe_error_message(e)}), 500


@app.route("/ready")
def ready():
    """Health/readiness endpoint for Docker/Kubernetes."""
    return jsonify({"status": "ok"}), 200
