# API errors for agent clients

JSON POST operations and the run-record and example GET endpoints return an error object with a human-readable `error` string and a `code` field. Existing clients can continue displaying `error`; agents can branch on `code` without parsing prose. The HTTP status is authoritative, and a successful HTTP response may still contain a scientific check status such as `needs_input` or `failed`. These do not imply simulation readiness.

| Code | HTTP | Meaning |
| --- | --- | --- |
| `invalid_request_size` | 400 | Content-Length is missing, invalid, zero, or greater than 30 MB. |
| `invalid_json` | 400 | Body is not valid UTF-8 JSON, or contains a nonfinite number. |
| `invalid_request` | 400 | JSON request fails operation validation. Inspect `error` for details; it is not a stable diagnostic code. |
| `origin_rejected` | 403 | The browser Origin is not the local workspace origin. |
| `route_not_found` | 404 | A POST route does not exist. |
| `run_not_found` | 404 | The requested run record is unavailable. |
| `example_unavailable` | 404 | The configured example cannot be read. |

This is a partial contract: file-download and other GET errors may still be plain text. Codes do not distinguish individual scientific validation failures. Do not infer a particular missing input from `invalid_request`; use the message and structured successful check result when available.
