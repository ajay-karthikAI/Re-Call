from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from config import get_settings
from services.transcript_import_service import normalize_transcript, parse_transcript


SUPPORTED_PROVIDERS = ("zoom", "meet", "teams")


class IntegrationError(RuntimeError):
    pass


class IntegrationConfigError(IntegrationError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    label: str
    client_id: str
    client_secret: str
    scopes: str
    authorize_url: str
    token_url: str
    token_uses_basic_auth: bool = False


@dataclass(frozen=True)
class ProviderTranscript:
    provider: str
    provider_id: str
    title: str
    transcript: str
    duration_seconds: int = 0
    metadata: Optional[dict[str, Any]] = None


def normalized_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    aliases = {"google": "meet", "google-meet": "meet", "microsoft": "teams", "ms-teams": "teams"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_PROVIDERS:
        raise IntegrationError("Unsupported transcript provider.")
    return normalized


def get_provider_config(provider: str) -> ProviderConfig:
    settings = get_settings()
    normalized = normalized_provider(provider)

    if normalized == "zoom":
        return ProviderConfig(
            provider="zoom",
            label="Zoom",
            client_id=settings.zoom_client_id,
            client_secret=settings.zoom_client_secret,
            scopes=settings.zoom_oauth_scopes,
            authorize_url="https://zoom.us/oauth/authorize",
            token_url="https://zoom.us/oauth/token",
            token_uses_basic_auth=True,
        )

    if normalized == "meet":
        return ProviderConfig(
            provider="meet",
            label="Google Meet",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=settings.google_oauth_scopes,
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
        )

    tenant_id = settings.microsoft_tenant_id or "common"
    return ProviderConfig(
        provider="teams",
        label="Microsoft Teams",
        client_id=settings.microsoft_client_id,
        client_secret=settings.microsoft_client_secret,
        scopes=settings.microsoft_oauth_scopes,
        authorize_url=f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize",
        token_url=f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    )


def is_configured(provider: str) -> bool:
    config = get_provider_config(provider)
    return bool(config.client_id and config.client_secret)


def redirect_uri(provider: str) -> str:
    settings = get_settings()
    return f"{settings.backend_public_url.rstrip('/')}/api/integrations/{normalized_provider(provider)}/callback"


def authorization_url(provider: str) -> str:
    config = get_provider_config(provider)
    if not config.client_id or not config.client_secret:
        raise IntegrationConfigError(f"{config.label} OAuth credentials are not configured.")

    params = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(config.provider),
        "scope": config.scopes,
        "state": config.provider,
    }
    if config.provider == "meet":
        params["access_type"] = "offline"
        params["prompt"] = "consent"
    return f"{config.authorize_url}?{urlencode(params)}"


def exchange_code(provider: str, code: str) -> dict[str, Any]:
    config = get_provider_config(provider)
    return _token_request(
        config,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(config.provider),
        },
    )


def refresh_access_token(provider: str, refresh_token: str) -> dict[str, Any]:
    config = get_provider_config(provider)
    return _token_request(config, {"grant_type": "refresh_token", "refresh_token": refresh_token})


def token_expiration(token_data: dict[str, Any]) -> Optional[datetime]:
    expires_in = token_data.get("expires_in")
    if expires_in is None:
        return None
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=max(seconds - 60, 0))


def fetch_provider_transcripts(
    provider: str,
    access_token: str,
    days: int = 30,
    limit: int = 5,
    teams_join_url: Optional[str] = None,
) -> list[ProviderTranscript]:
    normalized = normalized_provider(provider)
    if normalized == "zoom":
        return _fetch_zoom_transcripts(access_token, days, limit)
    if normalized == "meet":
        return _fetch_meet_transcripts(access_token, limit)
    return _fetch_teams_transcripts(access_token, teams_join_url, limit)


def _token_request(config: ProviderConfig, form_data: dict[str, str]) -> dict[str, Any]:
    data = dict(form_data)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    if config.token_uses_basic_auth:
        credentials = f"{config.client_id}:{config.client_secret}".encode("utf-8")
        headers["Authorization"] = f"Basic {base64.b64encode(credentials).decode('ascii')}"
    else:
        data["client_id"] = config.client_id
        data["client_secret"] = config.client_secret

    return _request_json("POST", config.token_url, data=data, headers=headers)


def _request_json(
    method: str,
    url: str,
    params: Optional[dict[str, Any]] = None,
    data: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    token: Optional[str] = None,
) -> dict[str, Any]:
    body = None
    request_headers = dict(headers or {})
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        body = urlencode(data).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    if params:
        query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
        if query:
            url = f"{url}{'&' if '?' in url else '?'}{query}"

    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=35) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise IntegrationError(_format_http_error(error.code, detail)) from error
    except URLError as error:
        raise IntegrationError(f"Provider connection failed: {error.reason}") from error

    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as error:
        raise IntegrationError("Provider returned a response Re: Call could not read.") from error
    if not isinstance(parsed, dict):
        raise IntegrationError("Provider returned an unexpected response.")
    return parsed


def _request_bytes(
    url: str,
    token: str,
    headers: Optional[dict[str, str]] = None,
) -> bytes:
    request_headers = dict(headers or {})
    request_headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=request_headers, method="GET")
    try:
        with urlopen(request, timeout=45) as response:
            return response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise IntegrationError(_format_http_error(error.code, detail)) from error
    except URLError as error:
        raise IntegrationError(f"Provider download failed: {error.reason}") from error


def _format_http_error(status_code: int, detail: str) -> str:
    cleaned = " ".join(detail.split())
    if len(cleaned) > 420:
        cleaned = f"{cleaned[:420]}..."
    return f"Provider API returned HTTP {status_code}. {cleaned}".strip()


def _fetch_zoom_transcripts(access_token: str, days: int, limit: int) -> list[ProviderTranscript]:
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    transcripts: list[ProviderTranscript] = []
    next_page_token = ""

    while len(transcripts) < limit:
        response = _request_json(
            "GET",
            "https://api.zoom.us/v2/users/me/recordings",
            params={
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "page_size": 30,
                "next_page_token": next_page_token,
            },
            token=access_token,
        )

        for meeting in response.get("meetings", []):
            if len(transcripts) >= limit:
                break
            transcript_file = _zoom_transcript_file(meeting.get("recording_files") or [])
            if not transcript_file:
                continue

            download_url = transcript_file.get("download_url")
            if not download_url:
                continue

            data = _request_bytes(download_url, access_token)
            filename = transcript_file.get("file_name") or "zoom-transcript.vtt"
            transcript, duration_seconds = parse_transcript(data, filename=filename, content_type="text/vtt")
            transcript = normalize_transcript(transcript)
            if len(transcript.split()) < 8:
                continue

            title = _meeting_title(
                "Zoom",
                meeting.get("topic"),
                meeting.get("start_time") or transcript_file.get("recording_start"),
            )
            transcripts.append(
                ProviderTranscript(
                    provider="zoom",
                    provider_id=str(meeting.get("uuid") or meeting.get("id") or transcript_file.get("id") or title),
                    title=title,
                    transcript=transcript,
                    duration_seconds=duration_seconds or int(meeting.get("duration") or 0) * 60,
                    metadata={"zoom_meeting_uuid": meeting.get("uuid"), "zoom_file_id": transcript_file.get("id")},
                )
            )

        next_page_token = response.get("next_page_token") or ""
        if not next_page_token:
            break

    return transcripts


def _zoom_transcript_file(recording_files: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for recording_file in recording_files:
        file_type = str(recording_file.get("file_type") or "").upper()
        file_extension = str(recording_file.get("file_extension") or "").upper()
        recording_type = str(recording_file.get("recording_type") or "").lower()
        if file_type == "TRANSCRIPT" or file_extension == "VTT" or recording_type == "audio_transcript":
            return recording_file
    return None


def _fetch_meet_transcripts(access_token: str, limit: int) -> list[ProviderTranscript]:
    transcripts: list[ProviderTranscript] = []
    page_token = ""

    while len(transcripts) < limit:
        records = _request_json(
            "GET",
            "https://meet.googleapis.com/v2/conferenceRecords",
            params={"pageSize": max(10, min(limit * 4, 100)), "pageToken": page_token},
            token=access_token,
        )

        for record in records.get("conferenceRecords", []):
            if len(transcripts) >= limit:
                break
            record_name = record.get("name")
            if not record_name:
                continue
            participants = _meet_participant_map(access_token, record_name)

            for transcript_meta in _meet_transcript_list(access_token, record_name):
                if len(transcripts) >= limit:
                    break
                transcript_name = transcript_meta.get("name")
                if not transcript_name:
                    continue
                transcript = _meet_transcript_text(access_token, transcript_name, participants)
                if len(transcript.split()) < 8:
                    continue

                title = _meeting_title(
                    "Google Meet",
                    _meet_space_title(record),
                    transcript_meta.get("startTime") or record.get("startTime"),
                )
                transcripts.append(
                    ProviderTranscript(
                        provider="meet",
                        provider_id=transcript_name,
                        title=title,
                        transcript=transcript,
                        duration_seconds=_duration_between(
                            transcript_meta.get("startTime") or record.get("startTime"),
                            transcript_meta.get("endTime") or record.get("endTime"),
                        ),
                        metadata={"conference_record": record_name, "transcript_name": transcript_name},
                    )
                )

        page_token = records.get("nextPageToken") or ""
        if not page_token:
            break

    return transcripts


def _meet_participant_map(access_token: str, record_name: str) -> dict[str, str]:
    participants: dict[str, str] = {}
    page_token = ""
    while True:
        response = _request_json(
            "GET",
            f"https://meet.googleapis.com/v2/{record_name}/participants",
            params={"pageSize": 100, "pageToken": page_token},
            token=access_token,
        )
        for participant in response.get("participants", []):
            name = participant.get("name")
            display_name = _meet_participant_display_name(participant)
            if name and display_name:
                participants[name] = display_name
        page_token = response.get("nextPageToken") or ""
        if not page_token:
            break
    return participants


def _meet_participant_display_name(participant: dict[str, Any]) -> str:
    for key in ("signedinUser", "anonymousUser", "phoneUser"):
        display_name = (participant.get(key) or {}).get("displayName")
        if display_name:
            return display_name
    return ""


def _meet_transcript_list(access_token: str, record_name: str) -> list[dict[str, Any]]:
    transcripts: list[dict[str, Any]] = []
    page_token = ""
    while True:
        response = _request_json(
            "GET",
            f"https://meet.googleapis.com/v2/{record_name}/transcripts",
            params={"pageSize": 100, "pageToken": page_token},
            token=access_token,
        )
        transcripts.extend(response.get("transcripts", []))
        page_token = response.get("nextPageToken") or ""
        if not page_token:
            break
    return transcripts


def _meet_transcript_text(access_token: str, transcript_name: str, participants: dict[str, str]) -> str:
    lines: list[str] = []
    page_token = ""
    while True:
        response = _request_json(
            "GET",
            f"https://meet.googleapis.com/v2/{transcript_name}/entries",
            params={"pageSize": 100, "pageToken": page_token},
            token=access_token,
        )
        for entry in response.get("transcriptEntries", []):
            text = normalize_transcript(entry.get("text") or "")
            if not text:
                continue
            participant = entry.get("participant")
            speaker = participants.get(participant, participant or "Speaker")
            lines.append(f"{speaker}: {text}")
        page_token = response.get("nextPageToken") or ""
        if not page_token:
            break
    return normalize_transcript("\n".join(lines))


def _fetch_teams_transcripts(
    access_token: str,
    teams_join_url: Optional[str],
    limit: int,
) -> list[ProviderTranscript]:
    if not teams_join_url or not teams_join_url.strip():
        raise IntegrationError("Paste a Teams meeting join URL so Microsoft Graph can find that meeting's transcript.")

    online_meeting = _teams_online_meeting(access_token, teams_join_url.strip())
    meeting_id = online_meeting.get("id")
    if not meeting_id:
        raise IntegrationError("Microsoft Graph found the meeting, but it did not return a meeting ID.")

    response = _request_json(
        "GET",
        f"https://graph.microsoft.com/v1.0/me/onlineMeetings/{quote(meeting_id, safe='')}/transcripts",
        token=access_token,
    )
    transcripts: list[ProviderTranscript] = []

    for transcript_meta in response.get("value", [])[:limit]:
        transcript_id = transcript_meta.get("id")
        if not transcript_id:
            continue
        content_url = (
            f"https://graph.microsoft.com/v1.0/me/onlineMeetings/{quote(meeting_id, safe='')}"
            f"/transcripts/{quote(transcript_id, safe='')}/content"
        )
        data = _request_bytes(content_url, access_token, headers={"Accept": "text/vtt"})
        transcript, duration_seconds = parse_transcript(data, filename="teams-transcript.vtt", content_type="text/vtt")
        transcript = normalize_transcript(transcript)
        if len(transcript.split()) < 8:
            continue

        title = _meeting_title(
            "Microsoft Teams",
            online_meeting.get("subject"),
            transcript_meta.get("createdDateTime") or online_meeting.get("startDateTime"),
        )
        transcripts.append(
            ProviderTranscript(
                provider="teams",
                provider_id=f"{meeting_id}:{transcript_id}",
                title=title,
                transcript=transcript,
                duration_seconds=duration_seconds
                or _duration_between(online_meeting.get("startDateTime"), online_meeting.get("endDateTime")),
                metadata={"teams_meeting_id": meeting_id, "teams_transcript_id": transcript_id},
            )
        )

    return transcripts


def _teams_online_meeting(access_token: str, teams_join_url: str) -> dict[str, Any]:
    filter_value = f"JoinWebUrl eq '{quote(teams_join_url, safe='')}'"
    response = _request_json(
        "GET",
        "https://graph.microsoft.com/v1.0/me/onlineMeetings",
        params={"$filter": filter_value},
        token=access_token,
    )
    meetings = response.get("value") or []
    if not meetings:
        raise IntegrationError(
            "Microsoft Graph could not find that Teams meeting. Use the exact Teams join URL and make sure your Microsoft account can access it."
        )
    return meetings[0]


def _meet_space_title(record: dict[str, Any]) -> str:
    space = record.get("space") or ""
    if isinstance(space, str) and space:
        return space.replace("spaces/", "Meet space ")
    return ""


def _meeting_title(provider: str, title: Optional[str], timestamp: Optional[str]) -> str:
    clean_title = normalize_transcript(title or "").replace("\n", " ")
    if not clean_title:
        clean_title = f"{provider} meeting"
    parsed_timestamp = _parse_timestamp(timestamp)
    if parsed_timestamp:
        return f"{clean_title} - {parsed_timestamp.strftime('%b')} {parsed_timestamp.day}, {parsed_timestamp.year}"[:240]
    return clean_title[:240]


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_between(start: Optional[str], end: Optional[str]) -> int:
    start_dt = _parse_timestamp(start)
    end_dt = _parse_timestamp(end)
    if not start_dt or not end_dt:
        return 0
    return max(int((end_dt - start_dt).total_seconds()), 0)
