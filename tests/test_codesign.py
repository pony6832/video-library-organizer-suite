import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import codesign  # noqa: E402


def test_signing_is_off_until_a_certificate_source_is_set():
    assert not codesign.configured({})
    assert codesign.configured({"VLO_SIGN_THUMBPRINT": "AB"})
    assert codesign.configured({"VLO_SIGN_PFX": "c.pfx"})
    assert codesign.configured({"VLO_SIGNTOOL_ARGS": "/dlib x.dll"})
    assert codesign.required({"VLO_SIGN_REQUIRED": "1"}) and not codesign.required({})


def test_pe_files_finds_every_executable_kind(tmp_path):
    for name in ("a.exe", "sub/b.dll", "sub/c.pyd", "d.txt", "e.EXE"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    found = {p.relative_to(tmp_path).as_posix() for p in codesign.pe_files([tmp_path])}
    assert found == {"a.exe", "sub/b.dll", "sub/c.pyd", "e.EXE"}


def test_nothing_is_signed_or_copied_without_a_certificate(tmp_path, monkeypatch):
    monkeypatch.setattr(codesign, "signature_status", lambda files: pytest.fail("must not inspect"))
    entries = [("python311.dll", str(tmp_path / "python311.dll"), "BINARY")]
    assert codesign.sign([tmp_path / "x.exe"], env={}) == []
    assert codesign.signed_toc(entries, tmp_path / "work", env={}) is entries


def test_onefile_binaries_are_replaced_by_signed_copies(tmp_path, monkeypatch):
    source = tmp_path / "site" / "pydantic_core.pyd"
    data = tmp_path / "site" / "base_library.zip"
    source.parent.mkdir()
    source.write_bytes(b"pe")
    data.write_bytes(b"zip")
    signed = []
    monkeypatch.setattr(codesign, "sign", lambda files, env: signed.extend(files) or files)
    entries = [("pydantic_core/_core.pyd", str(source), "EXTENSION"), ("base_library.zip", str(data), "DATA")]

    result = codesign.signed_toc(entries, tmp_path / "work", env={"VLO_SIGN_PFX": "c.pfx"})

    copy = tmp_path / "work" / "pydantic_core" / "_core.pyd"
    assert result == [("pydantic_core/_core.pyd", str(copy), "EXTENSION"), ("base_library.zip", str(data), "DATA")]
    assert signed == [copy] and copy.read_bytes() == b"pe"
    assert source.read_bytes() == b"pe"  # the virtual environment itself is never modified


def test_only_unsigned_files_are_signed(tmp_path, monkeypatch):
    files = [tmp_path / "ours.exe", tmp_path / "python311.dll"]
    monkeypatch.setattr(codesign, "signature_status", lambda paths: {
        files[0]: {"status": "NotSigned"}, files[1]: {"status": "Valid"}})
    sent = []
    monkeypatch.setattr(codesign, "_powershell", lambda script, payload: sent.append(payload) or [
        {"path": f, "status": "Valid", "signer": "AB"} for f in payload["files"]])

    done = codesign.sign(files, env={"VLO_SIGN_THUMBPRINT": "ab cd"})

    assert done == [files[0]]
    assert sent[0]["files"] == [str(files[0])] and sent[0]["thumbprint"] == "ABCD"
    assert sent[0]["timestamp"] == codesign.DEFAULT_TIMESTAMP_URL


def test_a_file_the_certificate_could_not_sign_fails_the_build(tmp_path, monkeypatch):
    target = tmp_path / "ours.exe"
    monkeypatch.setattr(codesign, "signature_status", lambda paths: {target: {"status": "NotSigned"}})
    monkeypatch.setattr(codesign, "_powershell", lambda script, payload: [
        {"path": str(target), "status": "UnknownError", "message": "no private key", "signer": None}])
    with pytest.raises(RuntimeError, match="no private key"):
        codesign.sign([target], env={"VLO_SIGN_THUMBPRINT": "AB"})


def _pe64(tmp_path, *, cert_offset, cert_size, length):
    data = bytearray(length)
    data[:2] = b"MZ"
    data[0x3C:0x40] = (0x80).to_bytes(4, "little")
    data[0x80:0x84] = b"PE\0\0"
    data[0x98:0x9A] = (0x20B).to_bytes(2, "little")
    entry = 0x98 + 112 + 32
    data[entry:entry + 4] = cert_offset.to_bytes(4, "little")
    data[entry + 4:entry + 8] = cert_size.to_bytes(4, "little")
    path = tmp_path / "x.dll"
    path.write_bytes(bytes(data))
    return path, entry


def test_dangling_certificate_entry_is_cleared(tmp_path):
    path, entry = _pe64(tmp_path, cert_offset=1024, cert_size=7408, length=1024)
    assert codesign.drop_dangling_certificate(path)
    assert path.read_bytes()[entry:entry + 8] == b"\0" * 8


def test_real_certificate_entry_is_kept(tmp_path):
    path, entry = _pe64(tmp_path, cert_offset=512, cert_size=256, length=1024)
    before = path.read_bytes()
    assert not codesign.drop_dangling_certificate(path)
    assert path.read_bytes() == before


def test_an_executable_named_explicitly_counts_whatever_its_extension(tmp_path):
    uninstaller = tmp_path / "uninst.e32.tmp"
    uninstaller.write_bytes(b"MZ\x90\x00")
    notes = tmp_path / "notes.tmp"
    notes.write_bytes(b"text")
    assert codesign.pe_files([uninstaller, notes]) == [uninstaller]
