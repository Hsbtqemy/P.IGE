"""SQLite schema of the new P.IGE model (see docs/modele.md).

Migrations are applied in order and tracked with ``PRAGMA user_version``.
Never edit a migration that has shipped: append a new one instead.
"""

from __future__ import annotations

# Each item is one migration; its index + 1 is the resulting user_version.
MIGRATIONS: tuple[str, ...] = (
    # ------------------------------------------------------------------ 1
    """
    CREATE TABLE spaces (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
        position    REAL NOT NULL DEFAULT 0,
        archived    INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
        created_at  TEXT NOT NULL
    );

    CREATE TABLE projects (
        id          TEXT PRIMARY KEY,
        space_id    TEXT NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
        parent_id   TEXT REFERENCES projects(id) ON DELETE RESTRICT,
        name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
        description TEXT,
        team        TEXT,
        state       TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'dormant', 'closed')),
        position    REAL NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        CHECK (parent_id IS NULL OR parent_id <> id)
    );
    CREATE INDEX projects_space ON projects(space_id, parent_id, position);

    -- At most one level of sub-project, and a sub-project lives in its parent's space.
    CREATE TRIGGER projects_one_level_insert BEFORE INSERT ON projects
    WHEN NEW.parent_id IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'parent project not found')
        WHERE NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.parent_id);
        SELECT RAISE(ABORT, 'sub-projects cannot have sub-projects')
        WHERE (SELECT parent_id FROM projects WHERE id = NEW.parent_id) IS NOT NULL;
        SELECT RAISE(ABORT, 'sub-project must be in its parent space')
        WHERE (SELECT space_id FROM projects WHERE id = NEW.parent_id) <> NEW.space_id;
    END;
    CREATE TRIGGER projects_one_level_update BEFORE UPDATE OF parent_id, space_id ON projects
    BEGIN
        SELECT RAISE(ABORT, 'parent project not found')
        WHERE NEW.parent_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.parent_id);
        SELECT RAISE(ABORT, 'sub-projects cannot have sub-projects')
        WHERE NEW.parent_id IS NOT NULL
          AND (SELECT parent_id FROM projects WHERE id = NEW.parent_id) IS NOT NULL;
        SELECT RAISE(ABORT, 'a project with sub-projects cannot become a sub-project')
        WHERE NEW.parent_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM projects WHERE parent_id = NEW.id);
        SELECT RAISE(ABORT, 'sub-project must be in its parent space')
        WHERE NEW.parent_id IS NOT NULL
          AND (SELECT space_id FROM projects WHERE id = NEW.parent_id) <> NEW.space_id;
    END;

    -- Moving a project to another space carries its sub-projects and everything attached.
    CREATE TRIGGER projects_space_cascade AFTER UPDATE OF space_id ON projects
    WHEN NEW.space_id <> OLD.space_id
    BEGIN
        UPDATE projects SET space_id = NEW.space_id WHERE parent_id = NEW.id;
        UPDATE tasks SET space_id = NEW.space_id
        WHERE project_id = NEW.id OR project_id IN (SELECT id FROM projects WHERE parent_id = NEW.id);
        UPDATE entries SET space_id = NEW.space_id
        WHERE project_id = NEW.id OR project_id IN (SELECT id FROM projects WHERE parent_id = NEW.id);
        UPDATE time_blocks SET space_id = NEW.space_id
        WHERE project_id = NEW.id OR project_id IN (SELECT id FROM projects WHERE parent_id = NEW.id);
    END;

    CREATE TABLE project_links (
        project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        position    REAL NOT NULL DEFAULT 0,
        url         TEXT NOT NULL,
        label       TEXT,
        PRIMARY KEY (project_id, url)
    );

    CREATE TABLE people (
        id            TEXT PRIMARY KEY,
        display_name  TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
        match_key     TEXT NOT NULL,
        email         TEXT,
        organisation  TEXT,
        role          TEXT,
        note          TEXT,
        directory_uid TEXT,
        created_at    TEXT NOT NULL
    );
    CREATE INDEX people_match ON people(match_key);
    CREATE UNIQUE INDEX people_email ON people(lower(email)) WHERE email IS NOT NULL;

    CREATE TABLE tags (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
        name_key    TEXT NOT NULL UNIQUE,
        pinned      INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
        position    REAL NOT NULL DEFAULT 0
    );

    -- rid: stable integer key for the full-text index (implicit rowids may be renumbered).
    CREATE TABLE tasks (
        rid             INTEGER PRIMARY KEY,
        id              TEXT NOT NULL UNIQUE,
        space_id        TEXT NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
        project_id      TEXT REFERENCES projects(id) ON DELETE RESTRICT,
        title           TEXT NOT NULL CHECK (length(trim(title)) > 0),
        note            TEXT,
        status          TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'in_progress', 'waiting', 'done')),
        waiting_on      TEXT REFERENCES people(id) ON DELETE RESTRICT,
        due_date        TEXT,
        position        REAL NOT NULL DEFAULT 0,
        origin_entry_id TEXT REFERENCES entries(id) ON DELETE SET NULL,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        status_since    TEXT NOT NULL,
        done_at         TEXT,
        CHECK ((status = 'done') = (done_at IS NOT NULL)),
        CHECK ((status = 'waiting') = (waiting_on IS NOT NULL))
    );
    CREATE INDEX tasks_project ON tasks(project_id, status, position);
    CREATE INDEX tasks_space ON tasks(space_id, status, position);
    CREATE INDEX tasks_waiting ON tasks(waiting_on) WHERE waiting_on IS NOT NULL;

    -- A task's space is its project's space.
    CREATE TRIGGER tasks_space_insert BEFORE INSERT ON tasks
    WHEN NEW.project_id IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'task space must match its project space')
        WHERE (SELECT space_id FROM projects WHERE id = NEW.project_id) IS NOT NEW.space_id;
    END;
    CREATE TRIGGER tasks_space_update BEFORE UPDATE OF project_id, space_id ON tasks
    WHEN NEW.project_id IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'task space must match its project space')
        WHERE (SELECT space_id FROM projects WHERE id = NEW.project_id) IS NOT NEW.space_id;
    END;

    CREATE TABLE task_steps (
        id          TEXT PRIMARY KEY,
        task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        label       TEXT NOT NULL CHECK (length(trim(label)) > 0),
        done        INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1)),
        position    REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX task_steps_task ON task_steps(task_id, position);

    CREATE TABLE entries (
        rid              INTEGER PRIMARY KEY,
        id               TEXT NOT NULL UNIQUE,
        space_id         TEXT NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
        project_id       TEXT REFERENCES projects(id) ON DELETE RESTRICT,
        task_id          TEXT REFERENCES tasks(id) ON DELETE SET NULL,
        kind             TEXT NOT NULL DEFAULT 'note'
                         CHECK (kind IN ('note', 'meeting', 'decision', 'activity')),
        title            TEXT NOT NULL DEFAULT '',
        body             TEXT NOT NULL DEFAULT '',
        entry_date       TEXT NOT NULL,
        start_time       TEXT,
        end_time         TEXT,
        decision_applied INTEGER CHECK (decision_applied IN (0, 1)),
        source           TEXT NOT NULL DEFAULT 'capture'
                         CHECK (source IN ('journal', 'writing', 'capture', 'mail', 'import')),
        mail_message_id  TEXT,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL,
        version          INTEGER NOT NULL DEFAULT 1,  -- text history (title/body)
        revision         INTEGER NOT NULL DEFAULT 1   -- any change, for concurrent edits
    );
    CREATE INDEX entries_date ON entries(entry_date, start_time);
    CREATE INDEX entries_project ON entries(project_id, entry_date);
    CREATE INDEX entries_task ON entries(task_id) WHERE task_id IS NOT NULL;
    CREATE UNIQUE INDEX entries_mail ON entries(mail_message_id) WHERE mail_message_id IS NOT NULL;

    CREATE TRIGGER entries_space_insert BEFORE INSERT ON entries
    WHEN NEW.project_id IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'entry space must match its project space')
        WHERE (SELECT space_id FROM projects WHERE id = NEW.project_id) IS NOT NEW.space_id;
    END;
    CREATE TRIGGER entries_space_update BEFORE UPDATE OF project_id, space_id ON entries
    WHEN NEW.project_id IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'entry space must match its project space')
        WHERE (SELECT space_id FROM projects WHERE id = NEW.project_id) IS NOT NEW.space_id;
    END;

    -- Previous versions of an entry (the current one lives in entries).
    CREATE TABLE entry_versions (
        entry_id    TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
        version     INTEGER NOT NULL,
        title       TEXT NOT NULL,
        body        TEXT NOT NULL,
        saved_at    TEXT NOT NULL,
        PRIMARY KEY (entry_id, version)
    );

    CREATE TABLE entry_people (
        entry_id    TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
        person_id   TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
        PRIMARY KEY (entry_id, person_id)
    );
    CREATE INDEX entry_people_person ON entry_people(person_id);

    CREATE TABLE task_people (
        task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        person_id   TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
        PRIMARY KEY (task_id, person_id)
    );
    CREATE INDEX task_people_person ON task_people(person_id);

    CREATE TABLE entry_tags (
        entry_id    TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
        tag_id      TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY (entry_id, tag_id)
    );
    CREATE INDEX entry_tags_tag ON entry_tags(tag_id);

    CREATE TABLE task_tags (
        task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        tag_id      TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY (task_id, tag_id)
    );
    CREATE INDEX task_tags_tag ON task_tags(tag_id);

    CREATE TABLE person_tags (
        person_id   TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
        tag_id      TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY (person_id, tag_id)
    );
    CREATE INDEX person_tags_tag ON person_tags(tag_id);

    -- Time: a block with end_at NULL is a running timer. Several may run at once.
    CREATE TABLE time_blocks (
        id            TEXT PRIMARY KEY,
        space_id      TEXT NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
        project_id    TEXT REFERENCES projects(id) ON DELETE RESTRICT,
        task_id       TEXT REFERENCES tasks(id) ON DELETE SET NULL,
        entry_id      TEXT REFERENCES entries(id) ON DELETE SET NULL,
        start_at      TEXT NOT NULL,
        end_at        TEXT,
        source        TEXT NOT NULL DEFAULT 'timer' CHECK (source IN ('timer', 'agenda', 'manual')),
        overlap_mode  TEXT NOT NULL DEFAULT 'shared' CHECK (overlap_mode IN ('shared', 'both', 'exclusive')),
        note          TEXT,
        validated     INTEGER NOT NULL DEFAULT 0 CHECK (validated IN (0, 1)),
        created_at    TEXT NOT NULL,
        CHECK (end_at IS NULL OR end_at > start_at)
    );
    CREATE INDEX time_blocks_start ON time_blocks(start_at);
    CREATE INDEX time_blocks_running ON time_blocks(end_at) WHERE end_at IS NULL;

    CREATE TRIGGER time_blocks_space_insert BEFORE INSERT ON time_blocks
    WHEN NEW.project_id IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'time block space must match its project space')
        WHERE (SELECT space_id FROM projects WHERE id = NEW.project_id) IS NOT NEW.space_id;
    END;
    CREATE TRIGGER time_blocks_space_update BEFORE UPDATE OF project_id, space_id ON time_blocks
    WHEN NEW.project_id IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'time block space must match its project space')
        WHERE (SELECT space_id FROM projects WHERE id = NEW.project_id) IS NOT NEW.space_id;
    END;

    -- Full-text search over entries and tasks (external content, kept in sync by triggers).
    CREATE VIRTUAL TABLE entries_fts USING fts5(
        title, body, content='entries', content_rowid='rid', tokenize='unicode61 remove_diacritics 2'
    );
    CREATE TRIGGER entries_fts_ai AFTER INSERT ON entries BEGIN
        INSERT INTO entries_fts(rowid, title, body) VALUES (NEW.rid, NEW.title, NEW.body);
    END;
    CREATE TRIGGER entries_fts_ad AFTER DELETE ON entries BEGIN
        INSERT INTO entries_fts(entries_fts, rowid, title, body) VALUES ('delete', OLD.rid, OLD.title, OLD.body);
    END;
    CREATE TRIGGER entries_fts_au AFTER UPDATE OF title, body ON entries BEGIN
        INSERT INTO entries_fts(entries_fts, rowid, title, body) VALUES ('delete', OLD.rid, OLD.title, OLD.body);
        INSERT INTO entries_fts(rowid, title, body) VALUES (NEW.rid, NEW.title, NEW.body);
    END;

    CREATE VIRTUAL TABLE tasks_fts USING fts5(
        title, note, content='tasks', content_rowid='rid', tokenize='unicode61 remove_diacritics 2'
    );
    CREATE TRIGGER tasks_fts_ai AFTER INSERT ON tasks BEGIN
        INSERT INTO tasks_fts(rowid, title, note) VALUES (NEW.rid, NEW.title, coalesce(NEW.note, ''));
    END;
    CREATE TRIGGER tasks_fts_ad AFTER DELETE ON tasks BEGIN
        INSERT INTO tasks_fts(tasks_fts, rowid, title, note) VALUES ('delete', OLD.rid, OLD.title, coalesce(OLD.note, ''));
    END;
    CREATE TRIGGER tasks_fts_au AFTER UPDATE OF title, note ON tasks BEGIN
        INSERT INTO tasks_fts(tasks_fts, rowid, title, note) VALUES ('delete', OLD.rid, OLD.title, coalesce(OLD.note, ''));
        INSERT INTO tasks_fts(rowid, title, note) VALUES (NEW.rid, NEW.title, coalesce(NEW.note, ''));
    END;
    """,
    # ------------------------------------------------------------------ 2
    # Calendars followed read-only (ICS feeds) and their events over a sliding window.
    # The feed address and credentials are stored encrypted by the server (source_enc):
    # this file alone never reveals them.
    """
    CREATE TABLE calendars (
        id            TEXT PRIMARY KEY,
        name          TEXT NOT NULL CHECK (length(trim(name)) > 0),
        color         TEXT NOT NULL DEFAULT '#3b5168',
        source_enc    TEXT NOT NULL,
        source_host   TEXT NOT NULL,
        has_password  INTEGER NOT NULL DEFAULT 0 CHECK (has_password IN (0, 1)),
        project_id    TEXT REFERENCES projects(id) ON DELETE SET NULL,
        active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        last_sync     TEXT,
        last_error    TEXT,
        last_attempt  TEXT,
        failures      INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL
    );

    CREATE TABLE calendar_events (
        id            TEXT PRIMARY KEY,
        calendar_id   TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
        uid           TEXT NOT NULL,
        start_at      TEXT NOT NULL,
        end_at        TEXT NOT NULL,
        all_day       INTEGER NOT NULL DEFAULT 0 CHECK (all_day IN (0, 1)),
        title         TEXT NOT NULL DEFAULT '',
        location      TEXT,
        description   TEXT,
        organizer     TEXT,
        attendees     TEXT NOT NULL DEFAULT '[]',
        status        TEXT,
        entry_id      TEXT REFERENCES entries(id) ON DELETE SET NULL,
        block_id      TEXT REFERENCES time_blocks(id) ON DELETE SET NULL
    );
    CREATE INDEX calendar_events_start ON calendar_events(start_at);
    CREATE INDEX calendar_events_calendar ON calendar_events(calendar_id);
    """,
    # ------------------------------------------------------------------ 3
    # Filing a meeting before taking a note: on the occurrence itself, or for the whole series
    # (every occurrence of a recurring event, those to come included).
    """
    ALTER TABLE calendar_events ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL;
    ALTER TABLE calendar_events ADD COLUMN space_id TEXT REFERENCES spaces(id) ON DELETE SET NULL;
    CREATE TABLE calendar_series (
        calendar_id TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
        uid         TEXT NOT NULL,
        project_id  TEXT REFERENCES projects(id) ON DELETE CASCADE,
        space_id    TEXT REFERENCES spaces(id) ON DELETE CASCADE,
        PRIMARY KEY (calendar_id, uid),
        CHECK ((project_id IS NULL) <> (space_id IS NULL))
    );
    """,
    # ------------------------------------------------------------------ 4
    # People of a project (or sub-project), with an optional role.
    """
    CREATE TABLE project_people (
        project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        person_id   TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
        role        TEXT CHECK (role IS NULL OR length(role) <= 120),
        position    INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (project_id, person_id)
    );
    CREATE INDEX project_people_person ON project_people(person_id);
    """,
    # ------------------------------------------------------------------ 5
    # The mails of a task's follow-up (« Suivi »): replies sent, mails received that were kept.
    # Those of one day are grouped under one journal entry, « Échange du … ».
    """
    CREATE TABLE task_mails (
        id          TEXT PRIMARY KEY,
        task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        entry_id    TEXT REFERENCES entries(id) ON DELETE SET NULL,
        day         TEXT NOT NULL,
        message_id  TEXT NOT NULL,
        direction   TEXT NOT NULL CHECK (direction IN ('sent', 'received')),
        sent_at     TEXT NOT NULL,
        author      TEXT NOT NULL DEFAULT '',
        recipients  TEXT NOT NULL DEFAULT '',
        subject     TEXT NOT NULL DEFAULT '',
        body        TEXT NOT NULL DEFAULT '',
        attachments TEXT NOT NULL DEFAULT '',
        UNIQUE (task_id, message_id)
    );
    CREATE INDEX task_mails_message ON task_mails(message_id);
    CREATE INDEX task_mails_entry ON task_mails(entry_id);
    """,
    # ------------------------------------------------------------------ 6
    # The code journal: a project linked to a git repository (GitHub). Each day with
    # pushed commits gives one journal entry, summed up by work item (« chantier » of
    # pilote); the work items themselves are read, not copied into tasks.
    """
    CREATE TABLE project_repos (
        project_id  TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        repo        TEXT NOT NULL CHECK (length(repo) BETWEEN 3 AND 200),
        branch      TEXT,
        last_sync   TEXT,
        last_error  TEXT,
        fiches      TEXT NOT NULL DEFAULT '[]',
        fiche_shas  TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE code_days (
        project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        day         TEXT NOT NULL,
        entry_id    TEXT REFERENCES entries(id) ON DELETE SET NULL,
        commits     TEXT NOT NULL DEFAULT '[]',
        summary     TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (project_id, day)
    );
    CREATE INDEX code_days_entry ON code_days(entry_id);
    """,
    # ------------------------------------------------------------------ 7
    # The last commit seen on each branch: a branch that did not move is not read again
    # (GitHub limits requests, 60 an hour without a token).
    """
    ALTER TABLE project_repos ADD COLUMN heads TEXT NOT NULL DEFAULT '{}';
    """,
    # ------------------------------------------------------------------ 8
    # The address of the repository's pilote export (journal.json on GitHub Pages): read
    # instead of the GitHub API when given — one static file, no limit, no token.
    """
    ALTER TABLE project_repos ADD COLUMN export_url TEXT;
    """,
    # ------------------------------------------------------------------ 9
    # The frame of a day: when it started and ended (declared, all optional), its
    # priorities (JSON list of {text, task_id, done}) and what to pick up the next day.
    """
    CREATE TABLE day_frames (
        day         TEXT PRIMARY KEY,
        started_at  TEXT,
        ended_at    TEXT,
        priorities  TEXT NOT NULL DEFAULT '[]',
        tomorrow    TEXT NOT NULL DEFAULT '',
        updated_at  TEXT NOT NULL,
        CHECK (ended_at IS NULL OR started_at IS NULL OR ended_at > started_at)
    );
    """,
    # ------------------------------------------------------------------ 10
    # Something planned that did not happen: kept as a trace, struck through, no time counted.
    """
    ALTER TABLE entries ADD COLUMN cancelled INTEGER NOT NULL DEFAULT 0 CHECK (cancelled IN (0, 1));
    """,
    # ------------------------------------------------------------------ 11
    # Notes taken for something of the agenda: a long text about a planned entry, or about
    # the short note of a calendar event (an event without a note points to the text itself).
    """
    ALTER TABLE entries ADD COLUMN about_entry_id TEXT REFERENCES entries(id) ON DELETE SET NULL;
    CREATE INDEX entries_about ON entries(about_entry_id) WHERE about_entry_id IS NOT NULL;
    """,
)

SCHEMA_VERSION = len(MIGRATIONS)
