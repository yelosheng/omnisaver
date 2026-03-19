## Repository quick guide for AI coding agents

This repository is a Python-based Twitter content archiver (web scraping first, no Twitter API required). Use Playwright as the primary scraper and fall back to static scraping when unavailable. Focus your changes on the service layer and file layout when implementing features.

Key entry points and where to make changes
- CLI: `main.py` — single-shot usage, verbose flag available for debugging.
- Web UI: `app.py` + `run_web.py` — Flask app, background queue is started on first request or by `run_web.py`.
- Services: `services/` — implement core logic here (notably `twitter_service.py`, `playwright_scraper.py`, `web_scraper.py`, `media_downloader.py`, `file_manager.py`).
- Models: `models/tweet.py`, `models/media_file.py` — canonical data shapes.

Important patterns and conventions
- Configuration: `services/config_manager.py` reads `config.ini` and env vars. Prefer using `ConfigManager.load_config()` to get runtime values (keys: `save_path`, `use_playwright`, `max_retries`, `timeout_seconds`).
- Scraping priority: Playwright (`use_playwright=True`) then `web_scraper`. `TwitterService` encapsulates this logic.
- Task queue: Flask app uses an in-process SQLite-backed task queue. Tasks are stored in `twitter_saver.db` (table `tasks`) and processed by a background thread (`queue_processor`). Changes that affect task lifecycle must update DB fields (status, next_retry_time, retry_count).
- File layout: saved tweets stored under `saved_tweets/YYYY-MM-DD_<tweet_id>/` with `content.txt`, `metadata.json`, `images/`, `videos/`, `thumbnails/`. Use `FileManager` helpers to create and normalize paths.

Testing, running and debugging
- Install deps: `pip install -r requirements.txt` and Playwright browsers `python -m playwright install chromium`.
- Run tests: `python -m pytest tests/` (tests exercise services; prefer small unit tests when adding logic).
- Run web app locally: `python run_web.py` (opens http://localhost:6201). Use `--no-browser` to skip opening the browser.
- CLI debug: `python main.py <url> --verbose`.

Project-specific behaviors to respect
- No Twitter API tokens: scraping-first design; do not reintroduce API auth without explicit task.
- Cross-platform path normalization: code frequently calls `normalize_path_cross_platform()` and `find_actual_tweet_directory()` — keep these behaviors when refactoring file paths.
- Retry policy: exponential backoff (2^retry_count minutes, capped) is implemented in `app.py` via `check_and_schedule_retry()` — preserve or update consistently.
- Media handling: thumbnails are preferred for previews; video thumbnail generation uses FFmpeg (tools/generate_missing_thumbnails.py).

Examples to reference in PRs
- To add a new scraper: follow `services/playwright_scraper.py` pattern and register it in `TwitterService.__init__`.
- To add API route: follow existing `/api/*` endpoints in `app.py`, update DB schema via `init_db()` if new columns required.
- To modify save format: update `services/file_manager.py` and ensure `saved_tweets/` consumers (UI, `find_actual_tweet_directory`) remain compatible.

Small checks before creating a PR
- Run the test suite: `python -m pytest tests/` and ensure no regressions.
- Smoke test CLI: `python main.py <sample_url> --no-media --verbose`.
- Smoke test web: `python run_web.py` then call `/api/submit` and check background processing and saved files.

If anything is unclear or you need a specific example (e.g., add a new field to the DB, extend Playwright scraping for threads), tell me which area and I'll add a focused code example or patch.
