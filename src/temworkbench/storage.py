import sqlite3
import time
from pathlib import Path

from .models import Job, JobRef


class Events:
    def __init__(self, filename: Path):
        self.db = sqlite3.connect(filename, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY,
                at REAL NOT NULL,
                event TEXT NOT NULL,
                session_id TEXT,
                command_id TEXT,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS events_job
            ON events(session_id, command_id, sequence);
        """)

    def append(self, event: str, job: Job | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO events(at, event, session_id, command_id, detail) VALUES(?,?,?,?,?)",
                (
                    time.time(),
                    event,
                    job.session_id if job else None,
                    str(job.command_id) if job else None,
                    job.model_dump_json() if job else None,
                ),
            )

    def get(self, ref: JobRef) -> Job | None:
        row = self.db.execute(
            """SELECT detail FROM events WHERE session_id = ? AND command_id = ?
            ORDER BY sequence DESC LIMIT 1""",
            (ref.session_id, str(ref.command_id)),
        ).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def latest(self, session_id: str | None = None) -> list[Job]:
        rows = self.db.execute(
            """SELECT detail FROM events WHERE sequence IN (
                SELECT MAX(sequence) FROM events
                WHERE command_id IS NOT NULL AND (? IS NULL OR session_id = ?)
                GROUP BY session_id, command_id
            ) ORDER BY sequence DESC""",
            (session_id, session_id),
        )
        return [Job.model_validate_json(row[0]) for row in rows]
