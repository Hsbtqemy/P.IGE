"""Calendar subscription management for syncing external ICS calendars."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

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
                create_project_per_calendar=item.get("create_project_per_calendar", True)
            )
            subscriptions.append(sub)
        
        return subscriptions
    
    def save_subscriptions(self, subscriptions: list[CalendarSubscription]) -> None:
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
                "create_project_per_calendar": sub.create_project_per_calendar
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
        create_project_per_calendar: bool = True
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
            create_project_per_calendar=create_project_per_calendar
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
    
    def delete_subscription(self, subscription_id: str, delete_entries: bool = False) -> None:
        """Delete a subscription and optionally its imported entries."""
        subs = self.list_subscriptions()
        sub_to_delete = None
        
        for sub in subs:
            if sub.id == subscription_id:
                sub_to_delete = sub
                break
        
        if not sub_to_delete:
            return
        
        # Delete imported entries if requested
        if delete_entries:
            for entry_id in sub_to_delete.event_mapping.values():
                try:
                    self.service.delete_entry(entry_id)
                except Exception as e:
                    logger.warning(f"Failed to delete entry {entry_id}: {e}")
        
        # Remove subscription
        subs = [s for s in subs if s.id != subscription_id]
        self.save_subscriptions(subs)
        
        logger.info(f"Deleted subscription {subscription_id}")
    
    def sync_subscription(self, subscription_id: str) -> dict:
        """Synchronize a calendar subscription.
        
        Returns dict with sync statistics:
        - added: number of new entries created
        - updated: number of entries updated
        - deleted: number of entries deleted
        - errors: list of error messages
        """
        subs = self.list_subscriptions()
        subscription = None
        
        for sub in subs:
            if sub.id == subscription_id:
                subscription = sub
                break
        
        if not subscription or not subscription.active:
            return {"added": 0, "updated": 0, "deleted": 0, "errors": ["Subscription not found or inactive"]}
        
        # Ensure project exists (create if needed)
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
            else:
                return {"added": 0, "updated": 0, "deleted": 0, "errors": ["No target project specified"]}
        
        try:
            # Import icalendar
            try:
                from icalendar import Calendar as ICalendar
            except ImportError:
                return {"added": 0, "updated": 0, "deleted": 0, "errors": ["icalendar library not installed"]}
            
            # Fetch ICS data
            ics_data = self._fetch_ics(subscription.source_url)
            if not ics_data:
                error_msg = f"Impossible de récupérer les données ICS depuis: {subscription.source_url[:100]}"
                if subscription.source_url.startswith(("http://", "https://")):
                    error_msg += "\n\nVérifiez que l'URL est correcte et accessible."
                    error_msg += "\n\nPour Google Calendar:"
                    error_msg += "\n1. Ouvrez les paramètres du calendrier"
                    error_msg += "\n2. Copiez l'URL 'Adresse secrète au format iCal'"
                else:
                    error_msg += f"\n\nVérifiez que le fichier existe: {subscription.source_url}"
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
                    dtstart = component.get('dtstart')
                    dtend = component.get('dtend')
                    
                    if not dtstart:
                        continue
                    
                    event_date = dtstart.dt
                    if isinstance(event_date, datetime):
                        event_date = event_date.date()
                    
                    # Skip past events if configured
                    if not subscription.import_past_events and event_date < today:
                        continue
                    
                    # Calculate hash for change detection
                    event_hash = self._hash_event(summary, description, event_date)
                    
                    current_events[uid] = {
                        "summary": summary,
                        "description": description,
                        "date": event_date,
                        "hash": event_hash,
                        "dtstart": dtstart,
                        "dtend": dtend
                    }
            
            # Synchronize
            stats = {"added": 0, "updated": 0, "deleted": 0, "errors": []}
            
            # Check for new and updated events
            for uid, event_data in current_events.items():
                entry_id = subscription.event_mapping.get(uid)
                
                if not entry_id:
                    # New event - create entry
                    try:
                        entry = self.service.add_entry(
                            project_id=subscription.project_id,
                            entry_type="activity",
                            title=event_data["summary"],
                            body=self._format_event_body(event_data),
                            tags=["calendar-sync", subscription.name],
                            entry_date=event_data["date"]
                        )
                        subscription.event_mapping[uid] = entry.id
                        stats["added"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to create entry for '{event_data['summary']}': {e}")
                else:
                    # Existing event - check for updates
                    try:
                        entries = self.service.storage.read_entries_meta()
                        entry = next((e for e in entries if e.id == entry_id), None)
                        
                        if entry:
                            # Check if content changed (simplified - check title and date)
                            needs_update = (
                                entry.title != event_data["summary"] or
                                entry.entry_date != event_data["date"].isoformat()
                            )
                            
                            if needs_update:
                                # Update entry
                                self.service.update_entry_meta(
                                    entry_id=entry_id,
                                    updates={
                                        "title": event_data["summary"],
                                        "entry_date": event_data["date"].isoformat()
                                    }
                                )
                                
                                # Update body
                                body_path = self.service.storage.data_dir / "entries" / f"{entry_id}.md"
                                new_body = self._format_event_body(event_data)
                                from pige.utils.io import write_text
                                write_text(body_path, new_body)
                                
                                stats["updated"] += 1
                        else:
                            # Entry was deleted locally, remove from mapping
                            del subscription.event_mapping[uid]
                    except Exception as e:
                        stats["errors"].append(f"Failed to update entry {entry_id}: {e}")
            
            # Check for deleted events (in mapping but not in current ICS)
            uids_to_remove = []
            for uid, entry_id in subscription.event_mapping.items():
                if uid not in current_events:
                    try:
                        self.service.delete_entry(entry_id)
                        uids_to_remove.append(uid)
                        stats["deleted"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to delete entry {entry_id}: {e}")
            
            # Clean up mapping
            for uid in uids_to_remove:
                del subscription.event_mapping[uid]
            
            # Update last sync time
            subscription.last_sync = datetime.now().isoformat()
            
            # Save updated subscription
            self.save_subscriptions(subs)
            
            logger.info(f"Synced subscription '{subscription.name}': +{stats['added']} ~{stats['updated']} -{stats['deleted']}")
            return stats
        
        except Exception as e:
            logger.error(f"Sync error for subscription {subscription_id}: {e}", exc_info=True)
            return {"added": 0, "updated": 0, "deleted": 0, "errors": [str(e)]}
    
    def _fetch_ics(self, source_url: str) -> bytes | None:
        """Fetch ICS data from URL or file path."""
        try:
            if source_url.startswith(("http://", "https://")):
                # Fetch from URL
                import urllib.request
                import ssl
                
                # Handle Google Calendar secret URLs (webcal://)
                if source_url.startswith("webcal://"):
                    source_url = source_url.replace("webcal://", "https://")
                
                logger.info(f"Fetching ICS from URL: {source_url[:50]}...")
                
                # Create SSL context (some calendars need this)
                ssl_context = ssl.create_default_context()
                
                # Add User-Agent header (some servers require it)
                req = urllib.request.Request(
                    source_url,
                    headers={
                        'User-Agent': 'PIGE-Calendar-Sync/1.0',
                        'Accept': 'text/calendar,text/plain,*/*'
                    }
                )
                
                with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                    data = response.read()
                    logger.info(f"Successfully fetched {len(data)} bytes")
                    return data
            else:
                # Read from local file
                logger.info(f"Reading ICS from file: {source_url}")
                path = Path(source_url)
                
                if not path.exists():
                    logger.error(f"File not found: {source_url}")
                    return None
                
                data = path.read_bytes()
                logger.info(f"Successfully read {len(data)} bytes from file")
                return data
                
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP Error {e.code} fetching ICS from {source_url}: {e.reason}")
            return None
        except urllib.error.URLError as e:
            logger.error(f"URL Error fetching ICS from {source_url}: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch ICS from {source_url}: {type(e).__name__}: {e}", exc_info=True)
            return None
    
    def _hash_event(self, summary: str, description: str, event_date: date) -> str:
        """Calculate hash of event for change detection."""
        content = f"{summary}|{description}|{event_date.isoformat()}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _format_event_body(self, event_data: dict) -> str:
        """Format event data as markdown body."""
        body = f"# {event_data['summary']}\n\n"
        body += f"**Date**: {event_data['date'].strftime('%d/%m/%Y')}\n\n"
        
        if event_data.get("description"):
            body += f"## Description\n\n{event_data['description']}\n\n"
        
        body += "---\n\n"
        body += "*Synchronisé depuis calendrier externe*\n"
        
        return body
    
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
