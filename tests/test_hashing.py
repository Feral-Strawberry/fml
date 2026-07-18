"""Tests für die Content-Hash-Bildung (ADR 0002)."""

from __future__ import annotations

import io

from feral.hashing import hash_bytes, hash_file, hash_stream

# Bekannte SHA-256-Referenzwerte.
SHA256_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SHA256_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_hash_bytes_known_vectors():
    assert hash_bytes(b"") == SHA256_EMPTY
    assert hash_bytes(b"abc") == SHA256_ABC


def test_hash_stream_matches_bytes():
    assert hash_stream(io.BytesIO(b"abc")) == SHA256_ABC


def test_hash_stream_small_chunk_size_is_equivalent():
    # Gestreamtes Hashen muss unabhängig von der Blockgröße dasselbe Ergebnis liefern.
    data = b"abc" * 1000
    assert hash_stream(io.BytesIO(data), chunk_size=7) == hash_bytes(data)


def test_hash_file_matches_bytes(tmp_path):
    path = tmp_path / "sample.bin"
    path.write_bytes(b"abc")
    assert hash_file(path) == SHA256_ABC
