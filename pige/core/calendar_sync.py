"""Calendar subscription management for syncing external ICS calendars."""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING
import urllib.error
import urllib.request

if TYPE_CHECKING:
    from pige.core.service import PigeService
    from pige.core.models import CalendarSubscription

logger = logging.getLogger(__name__)


class CalendarSyncManager:
    """Manages calendar subscriptions and synchronization."""
    
    def __init__(self, service: PigeService) -> None:
        self.service = service
        self.subscriptions_file = service.storage.data_dir / "calendar_subscriptions.json"
    
    def list_subscriptions(self) -> list[CalendarSubscription]:
        """List all calendar subscriptions."""
        from pige.core.models import CalendarSubscription
        from pige.utils.io import read_json
        
        if not self.subscriptions_file.exists():
            return []
        
        data = read_json(self.subscriptions_file, default=[])
        subscriptions = []
        
        for item in data:
            sub = CalendarSubscription(
                id=item["id"],
                name=item["name"],
                source_url=item["source_url"],
                project_id=item["project_id"],
                active=item.get("active", True),
                last_sync=item.get("last_sync"),
                sync_interval_minutes=item.get("sync_interval_minutes", 60),
                created_at=item.get("created_at", ""),
                event_mapping=item.get("event_mapping", {}),
                import_past_events=item.get("import_past_events", False),
                auto_sync=item.get("auto_sync", False),
                create_project_per_calendar=item.get("create_project_per_calendar", True),
                username=item.get("username"),
                password=item.get("password")
            )
            subscriptions.append(sub)
        
        return subscriptions
    
    def save_subscriptions(self, subscriptions: list[CalendarSubscription]) -> None:
        with self.service.storage.lock.hold():
            self._save_subscriptions(subscriptions)

    def _save_subscriptions(self, subscriptions: list[CalendarSubscription]) -> None:
        """Save subscriptions to disk."""
        from pige.utils.io import safe_write_json
        
        data = []
        for sub in subscriptions:
            data.append({
                "id": sub.id,
                "name": sub.name,
                "source_url": sub.source_url,
                "project_id": sub.project_id,
                "active": sub.active,
                "last_sync": sub.last_sync,
                "sync_interval_minutes": sub.sync_interval_minutes,
                "created_at": sub.created_at,
                "event_mapping": sub.event_mapping,
                "import_past_events": sub.import_past_events,
                "auto_sync": sub.auto_sync,
                "create_project_per_calendar": sub.create_project_per_calendar,
                "username": sub.username,
                "password": sub.password
            })
        
        safe_write_json(self.subscriptions_file, data)
        logger.info(f"Saved {len(subscriptions)} calendar subscriptions")
    
    def create_subscription(
        self,
        name: str,
        source_url: str,
        project_id: str | None = None,
        import_past_events: bool = False,
        auto_sync: bool = False,
        create_project_per_calendar: bool = True,
        username: str | None = None,
        password: str | None = None
    ) -> CalendarSubscription:
        """Create a new calendar subscription."""
        from pige.core.models import CalendarSubscription
        import uuid
        
        # If no project specified and create_project_per_calendar, create one
        if not project_id and create_project_per_calendar:
            project = self.service.create_project(
                name=f"📅 {name}",
                description=f"Calendrier externe synchronisé: {name}",
                tags=["calendar-sync", "external"]
            )
            project_id = project.id
        
        sub = CalendarSubscription(
            id=str(uuid.uuid4()),
            name=name,
            source_url=source_url,
            project_id=project_id,
            active=True,
            created_at=datetime.now().isoformat(),
            import_past_events=import_past_events,
            auto_sync=auto_sync,
            create_project_per_calendar=create_project_per_calendar,
            username=username,
            password=password
        )
        
        # Save
        subs = self.list_subscriptions()
        subs.append(sub)
        self.save_subscriptions(subs)
        
        logger.info(f"Created calendar subscription '{name}' -> project {project_id}")
        return sub
    
    def update_subscription(self, subscription_id: str, updates: dict) -> None:
        """Update a subscription."""
        subs = self.list_subscriptions()
        
        for sub in subs:
            if sub.id == subscription_id:
                for key, value in updates.items():
                    if hasattr(sub, key):
                        setattr(sub, key, value)
                break
        
        self.save_subscriptions(subs)
        logger.info(f"Updated subscription {subscription_id}")
    
    def delete_subscription(self, subscription_id: str, delete_events: bool = False) -> None:
        """Delete a subscription and optionally its imported events."""
        subs = self.list_subscriptions()
        sub_to_delete = None
        
        for sub in subs:
            if sub.id == subscription_id:
                sub_to_delete = sub
                break
        
        if not sub_to_delete:
            return
        
        # Delete imported events if requested
        if delete_events:
            from pige.core.storage import delete_calendar_events_by_subscription
            delete_calendar_events_by_subscription(self.service.storage, subscription_id)
        
        # Remove subscription
        subs = [s for s in subs if s.id != subscription_id]
        self.save_subscriptions(subs)
        
        logger.info(f"Deleted subscription {subscription_id}")
    
    def sync_subscription(self, subscription_id: str) -> dict:
        """Synchronize a calendar subscription.
        
        Returns dict with sync statistics:
        - added: number of new events created
        - updated: number of events updated
        - deleted: number of events deleted
        - errors: list of error messages
        """
        from pige.core.models import CalendarEvent
        from pige.core.storage import read_calendar_events
        
        subs = self.list_subscriptions()
        subscription = None
        
        for sub in subs:
            if sub.id == subscription_id:
                subscription = sub
                break
        
        if not subscription or not subscription.active:
            return {"added": 0, "updated": 0, "deleted": 0, "errors": ["Subscription not found or inactive"]}
        
        # Ensure project exists if needed (create if needed)
        if not subscription.project_id:
            if subscription.create_project_per_calendar:
                project = self.service.create_project(
                    name=f"📅 {subscription.name}",
                    description=f"Calendrier externe synchronisé: {subscription.name}",
                    tags=["calendar-sync", "external"]
                )
                subscription.project_id = project.id
                # Save subscription with new project_id
                for sub in subs:
                    if sub.id == subscription_id:
                        sub.project_id = project.id
                        break
                self.save_subscriptions(subs)
        
        try:
            # Import icalendar
            try:
                from icalendar import Calendar as ICalendar
            except ImportError:
                return {"added": 0, "updated": 0, "deleted": 0, "errors": ["icalendar library not installed"]}
            
            # Fetch ICS data
            ics_data = self._fetch_ics(subscription.source_url, subscription.username, subscription.password)
            if not ics_data:
                error_msg = f"Impossible de récupérer les données ICS depuis : {_redact_url(_normalize_calendar_url(subscription.source_url))}"
                if subscription.source_url.startswith(("http://", "https://")):
                    error_msg += "\n\nVérifiez que l'URL est correcte et accessible."
                    if not subscription.username:
                        error_msg += "\n\n⚠️ Si le calendrier nécessite une authentification:"
                        error_msg += "\n1. Éditez l'abonnement"
                        error_msg += "\n2. Ajoutez votre nom d'utilisateur et mot de passe"
                    error_msg += "\n\nPour Google Calendar:"
                    error_msg += "\n1. Ouvrez les paramètres du calendrier"
                    error_msg += "\n2. Copiez l'URL 'Adresse secrète au format iCal'"
                else:
                    error_msg += f"\n\nVérifiez que le fichier existe : {subscription.source_url}"
                return {"added": 0, "updated": 0, "deleted": 0, "errors": [error_msg]}
            
            # Parse calendar
            cal = ICalendar.from_ical(ics_data)
            
            # Extract current events from ICS
            current_events = {}  # uid -> event data
            today = date.today()
            
            for component in cal.walk():
                if component.name == "VEVENT":
                    uid = str(component.get('uid', ''))
                    if not uid:
                        continue
                    
                    summary = str(component.get('summary', 'Sans titre'))
                    description = str(component.get('description', ''))
                    location = str(component.get('location', '')) if component.get('location') else None
                    dtstart = component.get('dtstart')
                    dtend = component.get('dtend')
                    
                    if not dtstart:
                        continue
                    
                    event_date = dtstart.dt
                    start_time = None
                    end_date = None
                    end_time = None
                    
                    # Extract date/time information
                    if isinstance(event_date, datetime):
                        start_date_str = event_date.date().isoformat()
                        start_time = event_date.time().isoformat()
                        event_date_obj = event_date.date()
                    else:
                        start_date_str = event_date.isoformat()
                        event_date_obj = event_date
                    
                    if dtend:
                        if isinstance(dtend.dt, datetime):
                            end_date = dtend.dt.date().isoformat()
                            end_time = dtend.dt.time().isoformat()
                        else:
                            end_date = dtend.dt.isoformat()
                    
                    # Skip past events if configured
                    if not subscription.import_past_events and event_date_obj < today:
                        continue
                    
                    current_events[uid] = {
                        "summary": summary,
                        "description": description,
                        "location": location,
                        "start_date": start_date_str,
                        "start_time": start_time,
                        "end_date": end_date,
                        "end_time": end_time,
                    }
            
            # Load existing calendar events
            all_events = read_calendar_events(self.service.storage)
            subscription_events = {e.id: e for e in all_events if e.subscription_id == subscription_id}
            
            # Synchronize
            stats = {"added": 0, "updated": 0, "deleted": 0, "errors": []}
            now = datetime.now().isoformat()
            
            # Check for new and updated events
            for uid, event_data in current_events.items():
                existing_event = subscription_events.get(uid)
                
                if not existing_event:
                    # New event - create CalendarEvent
                    try:
                        new_event = CalendarEvent(
                            id=uid,
                            subscription_id=subscription_id,
                            title=event_data["summary"],
                            description=event_data["description"] if event_data["description"] else None,
                            start_date=event_data["start_date"],
                            end_date=event_data["end_date"],
                            start_time=event_data["start_time"],
                            end_time=event_data["end_time"],
                            location=event_data["location"],
                            created_at=now,
                            updated_at=now
                        )
                        
                        from pige.core.storage import upsert_calendar_event
                        upsert_calendar_event(self.service.storage, new_event)
                        stats["added"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to create event for '{event_data['summary']}': {e}")
                else:
                    # Existing event - check for updates
                    try:
                        needs_update = (
                            existing_event.title != event_data["summary"] or
                            existing_event.description != event_data["description"] or
                            existing_event.start_date != event_data["start_date"] or
                            existing_event.end_date != event_data["end_date"] or
                            existing_event.start_time != event_data["start_time"] or
                            existing_event.end_time != event_data["end_time"] or
                            existing_event.location != event_data["location"]
                        )
                        
                        if needs_update:
                            # Update event
                            updated_event = CalendarEvent(
                                id=existing_event.id,
                                subscription_id=subscription_id,
                                title=event_data["summary"],
                                description=event_data["description"] if event_data["description"] else None,
                                start_date=event_data["start_date"],
                                end_date=event_data["end_date"],
                                start_time=event_data["start_time"],
                                end_time=event_data["end_time"],
                                location=event_data["location"],
                                created_at=existing_event.created_at,
                                updated_at=now,
                                linked_entry_id=existing_event.linked_entry_id
                            )
                            
                            from pige.core.storage import upsert_calendar_event
                            upsert_calendar_event(self.service.storage, updated_event)
                            stats["updated"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to update event {uid}: {e}")
            
            # An empty feed while events exist locally is far more likely a server
            # glitch than a calendar emptied on purpose: keep everything.
            raw_event_count = sum(1 for c in cal.walk() if c.name == "VEVENT")
            if raw_event_count == 0 and subscription_events:
                logger.warning(
                    "Calendar '%s' returned no events; keeping the %d local ones",
                    subscription.name, len(subscription_events),
                )
                stats["errors"].append(
                    "Le calendrier n'a renvoyé aucun événement : rien n'a été supprimé localement."
                )
                subscription_events = {}

            # Check for deleted events (in storage but not in current ICS)
            for uid, event in subscription_events.items():
                if uid not in current_events:
                    try:
                        from pige.core.storage import delete_calendar_event
                        delete_calendar_event(self.service.storage, uid)
                        stats["deleted"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to delete event {uid}: {e}")
            
            # Update last sync time
            subscription.last_sync = now
            
            # Save updated subscription
            self.save_subscriptions(subs)
            
            logger.info(f"Synced subscription '{subscription.name}': +{stats['added']} ~{stats['updated']} -{stats['deleted']}")
            return stats
        
        except Exception as e:
            logger.error("Sync error for subscription %s: %s", subscription_id, type(e).__name__)
            return {"added": 0, "updated": 0, "deleted": 0, "errors": [str(e)]}
    
    def _fetch_ics(self, source_url: str, username: str | None = None, password: str | None = None) -> bytes | None:
        """Fetch ICS data from an http(s)/webcal URL or a local file path.

        Security rules: credentials are only ever sent over HTTPS, are dropped if
        the server redirects to another host, and a redirect may not downgrade to
        HTTP. Responses are capped at MAX_ICS_BYTES. Logs never contain the URL
        path or query, which often embed a private calendar token.
        """
        url = _normalize_calendar_url(source_url)
        shown = _redact_url(url)
        try:
            if url.startswith(("http://", "https://")):
                with_credentials = bool(username and password)
                if with_credentials and not url.startswith("https://"):
                    logger.error("Refusing to send calendar credentials over plain HTTP to %s", shown)
                    return None
                headers = {
                    "User-Agent": "PIGE-Calendar-Sync/1.0",
                    "Accept": "text/calendar,text/plain,*/*",
                }
                if with_credentials:
                    import base64

                    token = base64.b64encode(f"{username}:{password}".encode()).decode()
                    headers["Authorization"] = f"Basic {token}"
                logger.info("Fetching ICS from %s", shown)
                opener = urllib.request.build_opener(_SafeRedirectHandler())
                request = urllib.request.Request(url, headers=headers)
                with opener.open(request, timeout=30) as response:
                    data = response.read(MAX_ICS_BYTES + 1)
            else:
                path = Path(url)
                logger.info("Reading ICS from file %s", path.name)
                if not path.exists():
                    logger.error("Calendar file not found: %s", path.name)
                    return None
                with open(path, "rb") as handle:
                    data = handle.read(MAX_ICS_BYTES + 1)
            if len(data) > MAX_ICS_BYTES:
                logger.error("Calendar from %s exceeds %d bytes, ignored", shown, MAX_ICS_BYTES)
                return None
            logger.info("Fetched %d bytes from %s", len(data), shown)
            return data
        except urllib.error.HTTPError as e:
            logger.error("HTTP %s fetching calendar from %s: %s", e.code, shown, e.reason)
            return None
        except urllib.error.URLError as e:
            logger.error("Network error fetching calendar from %s: %s", shown, e.reason)
            return None
        except Exception as e:
            logger.error("Failed to fetch calendar from %s: %s", shown, type(e).__name__)
            return None
    
    def sync_all_active(self) -> dict[str, dict]:
        """Sync all active subscriptions with auto_sync enabled.
        
        Returns dict mapping subscription_id to sync stats.
        """
        subs = self.list_subscriptions()
        results = {}
        
        for sub in subs:
            if sub.active and sub.auto_sync:
                # Check if sync is needed based on interval
                needs_sync = True
                if sub.last_sync:
                    try:
                        last_sync_dt = datetime.fromisoformat(sub.last_sync)
                        minutes_since = (datetime.now() - last_sync_dt).total_seconds() / 60
                        needs_sync = minutes_since >= sub.sync_interval_minutes
                    except Exception:
                        pass
                
                if needs_sync:
                    results[sub.id] = self.sync_subscription(sub.id)
        
        return results


MAX_ICS_BYTES = 10 * 1024 * 1024


def _normalize_calendar_url(source_url: str) -> str:
    """webcal:// and webcals:// become https:// (webcal feeds are served over HTTPS)."""
    url = source_url.strip()
    for prefix in ("webcals://", "webcal://"):
        if url.lower().startswith(prefix):
            return "https://" + url[len(prefix):]
    return url


def _redact_url(url: str) -> str:
    """scheme://host/… : what logs and messages may show of a calendar URL."""
    import urllib.parse

    if not url.startswith(("http://", "https://")):
        return Path(url).name or "(fichier)"
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or "?"
    return f"{parts.scheme}://{host}/…"


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects without leaking credentials or downgrading to HTTP."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        import urllib.parse

        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if new.scheme not in ("http", "https"):
            raise urllib.error.HTTPError(newurl, code, "Redirect to a non-HTTP URL refused", headers, fp)
        has_auth = req.has_header("Authorization") or "Authorization" in getattr(req, "unredirected_hdrs", {})
        if has_auth and new.scheme != "https":
            raise urllib.error.HTTPError(newurl, code, "Redirect from HTTPS to HTTP refused", headers, fp)
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        same_origin = (
            (new.hostname or "").lower() == (old.hostname or "").lower()
            and new.scheme == old.scheme
            and (new.port or 0) == (old.port or 0)
        )
        if new_req is not None and not same_origin:
            new_req.headers.pop("Authorization", None)
            new_req.unredirected_hdrs.pop("Authorization", None)
        return new_req
