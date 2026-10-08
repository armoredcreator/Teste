from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Item, State


class Database:
    """SQLite source of truth for one ArmoredCreator runtime."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS items (
            content_id TEXT PRIMARY KEY,
            telegram_message_id TEXT NOT NULL UNIQUE,
            source_id TEXT NOT NULL DEFAULT 'telegram',
            topic_id INTEGER,
            topic_name TEXT,
            original_url TEXT,
            state TEXT NOT NULL,
            original_path TEXT NOT NULL,
            original_sha256 TEXT,
            working_path TEXT,
            result_path TEXT,
            affiliate_name TEXT,
            affiliate_url TEXT,
            publication_caption TEXT,
            affiliate_urls_json TEXT NOT NULL DEFAULT '[]',
            ia_context_json TEXT NOT NULL DEFAULT '{}',
            attempts INTEGER NOT NULL DEFAULT 0,
            recovery_count INTEGER NOT NULL DEFAULT 0,
            cleanup_completed INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS state_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id TEXT NOT NULL,
            old_state TEXT,
            new_state TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS publications (
            content_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            published_message_id TEXT,
            confirmed INTEGER NOT NULL DEFAULT 0,
            verification_status TEXT NOT NULL DEFAULT 'PENDING',
            destination_chat_id TEXT,
            destination_topic_id INTEGER,
            verified_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sync_topics (
            topic_id INTEGER PRIMARY KEY,
            topic_name TEXT NOT NULL,
            last_seen_message_id INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS caption_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            candidate_index INTEGER NOT NULL,
            caption TEXT NOT NULL,
            policy_valid INTEGER NOT NULL,
            rejection_reason TEXT,
            score REAL NOT NULL DEFAULT 0,
            selected INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(content_id, batch_id, candidate_index)
        );
        CREATE TABLE IF NOT EXISTS runtime_locks (
            name TEXT PRIMARY KEY,
            pid INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL
        );
        """)
        self.conn.commit()

    @staticmethod
    def _optional_path(value) -> Path | None:
        if value is None or not str(value).strip() or str(value).lower() == "none":
            return None
        return Path(str(value))

    def reserve_item(self, telegram_message_id: str, source_id: str="telegram",
                     topic_id: int|None=None, topic_name: str|None=None,
                     original_url: str|None=None, original_path: Path|None=None) -> str:
        item_id=str(telegram_message_id)
        self.conn.execute(
            "INSERT INTO items(content_id,telegram_message_id,source_id,topic_id,topic_name,original_url,state,original_path) VALUES(?,?,?,?,?,?,?,?)",
            (item_id,item_id,str(source_id),topic_id,topic_name,original_url,State.RECEIVED.value,str(original_path or "")),
        )
        self.conn.execute("INSERT INTO state_events(content_id,new_state,reason) VALUES(?,?,?)",
                          (item_id,State.RECEIVED.value,"ingest-reserved"))
        self.conn.commit()
        return item_id

    def finalize_original_path(self,item_id:str,path:Path,sha256:str)->None:
        self.conn.execute("UPDATE items SET original_path=?,original_sha256=?,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",
                          (str(path),sha256,str(item_id)))
        self.conn.commit()

    def get(self,item_id:str)->Item:
        row=self.conn.execute("SELECT * FROM items WHERE content_id=?",(str(item_id),)).fetchone()
        if row is None: raise KeyError(item_id)
        return Item(
            row["content_id"],row["telegram_message_id"],State(row["state"]),
            Path(row["original_path"]).parent,Path(row["original_path"]),
            self._optional_path(row["working_path"]),self._optional_path(row["result_path"]),
            row["affiliate_name"],row["affiliate_url"],row["source_id"],row["original_url"],
            row["topic_id"],row["topic_name"],row["original_sha256"],row["attempts"],
            row["recovery_count"],bool(row["cleanup_completed"]),row["publication_caption"],
            tuple(json.loads(row["affiliate_urls_json"] or "[]")),
            json.loads(row["ia_context_json"] or "{}"),
        )

    def record_attempt(self,item_id:str)->None:
        self.conn.execute("UPDATE items SET attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(item_id,))
        self.conn.commit()

    def record_recovery(self,item_id:str)->None:
        self.conn.execute("UPDATE items SET recovery_count=recovery_count+1,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(item_id,))
        self.conn.commit()

    def transition(self,item_id:str,new_state:State,reason:str="")->None:
        old=self.get(item_id).state
        self.conn.execute("UPDATE items SET state=?,last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(new_state.value,item_id))
        self.conn.execute("INSERT INTO state_events(content_id,old_state,new_state,reason) VALUES(?,?,?,?)",(item_id,old.value,new_state.value,reason))
        self.conn.commit()

    def mark_vision_waiting(self,item_id:str,reason:str)->None:
        old=self.get(item_id).state
        self.conn.execute("UPDATE items SET state=?,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(State.WAITING_VISION.value,reason,item_id))
        self.conn.execute("INSERT INTO state_events(content_id,old_state,new_state,reason) VALUES(?,?,?,?)",(item_id,old.value,State.WAITING_VISION.value,reason))
        self.conn.commit()

    def set_vision(self,item_id:str,affiliate_name:str,affiliate_url:str,affiliate_urls=(),publication_caption=None,ia_context=None)->None:
        links=list(dict.fromkeys(str(x).strip() for x in (affiliate_urls or ()) if str(x).strip()))
        if not links and affiliate_url: links=[str(affiliate_url).strip()]
        self.conn.execute(
            "UPDATE items SET affiliate_name=?,affiliate_url=?,publication_caption=?,affiliate_urls_json=?,ia_context_json=?,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",
            (affiliate_name,affiliate_url,publication_caption,json.dumps(links,ensure_ascii=False),json.dumps(ia_context or {},ensure_ascii=False,default=str),item_id))
        self.conn.commit()

    def set_ia_context(self,item_id:str,context:dict|None)->None:
        self.conn.execute("UPDATE items SET ia_context_json=?,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(json.dumps(context or {},ensure_ascii=False,default=str),item_id)); self.conn.commit()

    def set_caption(self,item_id:str,caption:str)->None:
        self.conn.execute("UPDATE items SET publication_caption=?,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(str(caption),item_id)); self.conn.commit()

    def set_working(self,item_id:str,path:Path|None)->None:
        self.conn.execute("UPDATE items SET working_path=?,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(str(path) if path else None,item_id)); self.conn.commit()

    def set_result(self,item_id:str,path:Path)->None:
        self.conn.execute("UPDATE items SET result_path=?,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(str(path),item_id)); self.conn.commit()

    def fail(self,item_id:str,error:str)->None:
        self.conn.execute("UPDATE items SET state=?,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(State.FAILED.value,error,item_id))
        self.conn.execute("INSERT INTO state_events(content_id,new_state,reason) VALUES(?,?,?)",(item_id,State.FAILED.value,error)); self.conn.commit()

    def mark_cleanup_completed(self,item_id:str)->None:
        self.conn.execute("UPDATE items SET cleanup_completed=1,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(item_id,)); self.conn.commit()

    def publication_started(self,item_id:str,destination_chat_id=None,destination_topic_id=None)->None:
        self.conn.execute(
            "INSERT INTO publications(content_id,idempotency_key,destination_chat_id,destination_topic_id) VALUES(?,?,?,?) ON CONFLICT(content_id) DO UPDATE SET destination_chat_id=COALESCE(excluded.destination_chat_id,publications.destination_chat_id),destination_topic_id=COALESCE(excluded.destination_topic_id,publications.destination_topic_id),updated_at=CURRENT_TIMESTAMP",
            (item_id,f"armoredcreator:content:{item_id}",destination_chat_id,destination_topic_id)); self.conn.commit()

    def publication_send_started(self,item_id:str)->None:
        self.conn.execute("UPDATE publications SET verification_status='SENT_UNVERIFIED',updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(item_id,)); self.conn.commit()

    def publication_message_sent(self,item_id:str,message_id:str)->None:
        self.conn.execute("UPDATE publications SET published_message_id=?,confirmed=0,verification_status='SENT_UNVERIFIED',updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(message_id,item_id)); self.conn.commit()

    def publication_confirmed(self,item_id:str,message_id:str)->None:
        self.conn.execute("UPDATE publications SET published_message_id=?,confirmed=1,verification_status='CONFIRMED',verified_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE content_id=?",(message_id,item_id)); self.conn.commit()

    def publication(self,item_id:str):
        return self.conn.execute("SELECT * FROM publications WHERE content_id=?",(str(item_id),)).fetchone()

    def acquire_runtime_lock(self,name="coordinator")->None:
        now=datetime.now(timezone.utc).isoformat(); pid=os.getpid()
        row=self.conn.execute("SELECT pid FROM runtime_locks WHERE name=?",(name,)).fetchone()
        if row is not None:
            owner=int(row["pid"]); alive=owner==pid
            if not alive:
                try: os.kill(owner,0); alive=True
                except OSError: alive=False
            if alive: raise RuntimeError(f"runtime-lock-active: {name} is already owned by PID {owner}")
        self.conn.execute("INSERT INTO runtime_locks(name,pid,started_at,heartbeat_at) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET pid=excluded.pid,started_at=excluded.started_at,heartbeat_at=excluded.heartbeat_at",(name,pid,now,now)); self.conn.commit()

    def heartbeat_runtime_lock(self,name="coordinator")->None:
        self.conn.execute("UPDATE runtime_locks SET heartbeat_at=CURRENT_TIMESTAMP WHERE name=? AND pid=?",(name,os.getpid())); self.conn.commit()

    def release_runtime_lock(self,name="coordinator")->None:
        self.conn.execute("DELETE FROM runtime_locks WHERE name=? AND pid=?",(name,os.getpid())); self.conn.commit()

    def close(self)->None:
        try:
            self.conn.commit()
            try:self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.OperationalError:pass
        finally:self.conn.close()
