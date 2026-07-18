-- Migration 0005: Smart Folders (Stufe 3.3, ADR 0018).
-- Ein Smart Folder ist NUR ein Name + Filterausdruck als Text; ausgewertet
-- wird live bei jedem Öffnen. Die Grammatik (UND + Negation) ist in ADR 0018
-- festgeschrieben — Erweiterungen dürfen gespeicherte Ausdrücke nie umdeuten.

CREATE TABLE IF NOT EXISTS smart_folders (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    expression TEXT NOT NULL,
    created_at TEXT NOT NULL,                  -- ISO-8601 UTC
    updated_at TEXT NOT NULL
);
