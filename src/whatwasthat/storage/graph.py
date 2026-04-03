"""Kuzu 그래프 DB 래퍼 - 스키마 초기화, 트리플 CRUD, Cypher 쿼리."""

import uuid
from datetime import datetime
from pathlib import Path

import kuzu

from whatwasthat.models import Entity, Session, Triple


class GraphStore:
    """Kuzu 그래프 DB 래퍼."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: kuzu.Database | None = None
        self._conn: kuzu.Connection | None = None

    def _ensure_connection(self) -> kuzu.Connection:
        if self._conn is None:
            self._db = kuzu.Database(str(self._db_path))
            self._conn = kuzu.Connection(self._db)
        return self._conn

    def initialize(self) -> None:
        """스키마 초기화."""
        conn = self._ensure_connection()
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Entity (
                id STRING, name STRING, type STRING,
                created_at TIMESTAMP DEFAULT timestamp('2024-01-01'),
                PRIMARY KEY (id)
            )
        """)
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Session (
                id STRING, source STRING DEFAULT 'claude-code',
                created_at TIMESTAMP DEFAULT timestamp('2024-01-01'),
                summary STRING DEFAULT '',
                PRIMARY KEY (id)
            )
        """)
        conn.execute("""
            CREATE REL TABLE IF NOT EXISTS RELATION (
                FROM Entity TO Entity,
                type STRING, session_id STRING,
                temporal STRING DEFAULT '',
                confidence DOUBLE DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT timestamp('2024-01-01')
            )
        """)
        conn.execute("""
            CREATE REL TABLE IF NOT EXISTS APPEARS_IN (
                FROM Entity TO Session
            )
        """)

    def _ensure_entity(self, name: str, entity_type: str) -> str:
        """엔티티가 없으면 생성, 있으면 ID 반환."""
        conn = self._ensure_connection()
        result = conn.execute(
            "MATCH (e:Entity) WHERE e.name = $name RETURN e.id",
            parameters={"name": name},
        )
        while result.has_next():
            return result.get_next()[0]
        entity_id = str(uuid.uuid4())[:8]
        conn.execute(
            "CREATE (e:Entity {id: $id, name: $name, type: $type})",
            parameters={"id": entity_id, "name": name, "type": entity_type},
        )
        return entity_id

    def _ensure_session(self, session_id: str) -> None:
        """세션 노드가 없으면 생성."""
        conn = self._ensure_connection()
        result = conn.execute(
            "MATCH (s:Session) WHERE s.id = $id RETURN s.id",
            parameters={"id": session_id},
        )
        if not result.has_next():
            conn.execute(
                "CREATE (s:Session {id: $id})",
                parameters={"id": session_id},
            )

    def add_triples(self, session_id: str, triples: list[Triple]) -> None:
        """세션에 트리플 리스트 저장."""
        conn = self._ensure_connection()
        self._ensure_session(session_id)
        for triple in triples:
            subj_id = self._ensure_entity(triple.subject, triple.subject_type)
            obj_id = self._ensure_entity(triple.object, triple.object_type)
            conn.execute(
                """
                MATCH (s:Entity), (o:Entity)
                WHERE s.id = $sid AND o.id = $oid
                CREATE (s)-[:RELATION {
                    type: $type, session_id: $session_id,
                    temporal: $temporal, confidence: $confidence
                }]->(o)
                """,
                parameters={
                    "sid": subj_id, "oid": obj_id,
                    "type": triple.predicate, "session_id": session_id,
                    "temporal": triple.temporal or "",
                    "confidence": triple.confidence,
                },
            )
            for eid in (subj_id, obj_id):
                conn.execute(
                    """
                    MATCH (e:Entity), (sess:Session)
                    WHERE e.id = $eid AND sess.id = $sid
                    MERGE (e)-[:APPEARS_IN]->(sess)
                    """,
                    parameters={"eid": eid, "sid": session_id},
                )

    def get_session_triples(self, session_id: str) -> list[Triple]:
        """세션의 모든 트리플 조회."""
        conn = self._ensure_connection()
        result = conn.execute(
            """
            MATCH (s:Entity)-[r:RELATION]->(o:Entity)
            WHERE r.session_id = $session_id
            RETURN s.name, s.type, r.type, o.name, o.type, r.temporal, r.confidence
            """,
            parameters={"session_id": session_id},
        )
        triples: list[Triple] = []
        while result.has_next():
            row = result.get_next()
            triples.append(Triple(
                subject=row[0], subject_type=row[1],
                predicate=row[2],
                object=row[3], object_type=row[4],
                temporal=row[5] if row[5] else None,
                confidence=row[6],
            ))
        return triples

    def get_entity_history(self, entity_name: str) -> list[Triple]:
        """엔티티의 시간순 변천 이력 조회."""
        conn = self._ensure_connection()
        result = conn.execute(
            """
            MATCH (s:Entity)-[r:RELATION]->(o:Entity)
            WHERE s.name = $name OR o.name = $name
            RETURN s.name, s.type, r.type, o.name, o.type, r.temporal, r.confidence
            """,
            parameters={"name": entity_name},
        )
        triples: list[Triple] = []
        while result.has_next():
            row = result.get_next()
            triples.append(Triple(
                subject=row[0], subject_type=row[1],
                predicate=row[2],
                object=row[3], object_type=row[4],
                temporal=row[5] if row[5] else None,
                confidence=row[6],
            ))
        return triples

    def find_related_sessions(self, entity_names: list[str]) -> list[Session]:
        """엔티티와 관련된 세션 목록 조회."""
        conn = self._ensure_connection()
        sessions: dict[str, Session] = {}
        for name in entity_names:
            result = conn.execute(
                """
                MATCH (e:Entity)-[:APPEARS_IN]->(s:Session)
                WHERE e.name = $name
                RETURN s.id, s.source, s.summary
                """,
                parameters={"name": name},
            )
            while result.has_next():
                row = result.get_next()
                sid = row[0]
                if sid not in sessions:
                    sessions[sid] = Session(
                        id=sid,
                        source=row[1] or "claude-code",
                        created_at=datetime.now(),
                        summary=row[2] or "",
                    )
        return list(sessions.values())
