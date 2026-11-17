import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import urllib.error

from PIL import Image
import pytest

from media_catalog import app_logging, sqlite_utils
from media_catalog import supervisor as supervisor_module
from media_catalog.database import CatalogDatabase
from media_catalog.inference import (
    AnalysisError,
    FfmpegImagePreparer,
    LocalAnalyzer,
    OllamaHttpClient,
    OllamaUnavailable,
    _ollama_base_url,
)
from media_catalog.single_instance import hold
from media_catalog.source_guard import (
    SourceIntegrityError,
    capture_source,
    check_snapshot_matches_record,
    verify_source_unchanged,
)

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "packaging"))
import release_docs  # noqa: E402

ANALYSIS_JSON = json.dumps(
    {"description": "海邊", "highlights": ["浪"], "keywords": ["海"]}, ensure_ascii=False
)


# --- source fingerprints -------------------------------------------------

def test_known_size_and_mtime_reuse_the_fingerprint_without_reading(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"abcd")
    stat = source.stat()
    monkeypatch.setattr(
        "media_catalog.source_guard.sha256_file",
        lambda *_: pytest.fail("the file must not be read again"),
    )

    snapshot = capture_source(source, known=(stat.st_size, stat.st_mtime_ns, "stored"))

    assert snapshot.sha256 == "stored"


def test_changed_size_is_hashed_again_and_rejected(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"abcd")
    database = CatalogDatabase(tmp_path / "catalog.sqlite")
    stat = source.stat()
    record = database.upsert_discovered(
        source, "stored", "video/mp4", size=stat.st_size, mtime_ns=stat.st_mtime_ns
    )
    assert database.source_stat(record.id) == (stat.st_size, stat.st_mtime_ns)
    source.write_bytes(b"abcdef")

    snapshot = capture_source(source, known=(*database.source_stat(record.id), "stored"))

    with pytest.raises(SourceIntegrityError, match="指紋"):
        check_snapshot_matches_record(record, snapshot)


def test_post_analysis_check_detects_a_modified_source(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"abcd")
    database = CatalogDatabase(tmp_path / "catalog.sqlite")
    record = database.upsert_discovered(source, "stored", "video/mp4")
    snapshot = capture_source(source)
    assert verify_source_unchanged(record, snapshot) == snapshot

    source.write_bytes(b"abcdef")

    with pytest.raises(SourceIntegrityError, match="大小"):
        verify_source_unchanged(record, snapshot)


# --- SQLite journal ------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="WAL is only enabled on Windows")
def test_local_database_uses_wal_and_reads_during_a_write(tmp_path):
    path = tmp_path / "catalog.sqlite"
    if not sqlite_utils.wal_is_safe(path):
        pytest.skip("temporary directory is not on a local fixed disk")
    CatalogDatabase(path)
    reader = sqlite3.connect(path, timeout=0)
    writer = sqlite3.connect(path)
    try:
        assert reader.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE media_records SET status = status")
        assert reader.execute("SELECT COUNT(*) FROM media_records").fetchone()[0] == 0
    finally:
        writer.rollback()
        writer.close()
        reader.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive rules")
def test_network_and_synced_folders_keep_the_rollback_journal(tmp_path, monkeypatch):
    assert not sqlite_utils.wal_is_safe(r"\\nas\share\媒體整理成果\catalog.sqlite")
    monkeypatch.setenv("OneDrive", str(tmp_path / "OneDrive"))
    assert not sqlite_utils.wal_is_safe(tmp_path / "OneDrive" / "影片" / "catalog.sqlite")


# --- Ollama over HTTP ----------------------------------------------------

class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_ollama_http_request_carries_images_and_disables_thinking(tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg-bytes")
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data)
        return _Response(json.dumps({"response": ANALYSIS_JSON}).encode("utf-8"))

    client = OllamaHttpClient(base_url="http://127.0.0.1:11434", opener=opener)
    analyzer = LocalAnalyzer(
        model="qwen3.5:9b",
        http_client=client,
        runner=lambda *_a, **_k: pytest.fail("the CLI must not run"),
        timeout=42,
    )

    analysis = analyzer.analyze_frames([frame])

    assert analysis.description == "海邊"
    assert seen["url"] == "http://127.0.0.1:11434/api/generate"
    assert seen["timeout"] == 42
    assert seen["body"]["images"] == [base64.b64encode(b"jpeg-bytes").decode("ascii")]
    assert seen["body"]["think"] is False
    assert seen["body"]["format"] == "json" and seen["body"]["stream"] is False


def test_unreachable_ollama_server_falls_back_to_the_cli(tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg-bytes")
    calls = []

    def opener(_request, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

    def runner(arguments, **_kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout=ANALYSIS_JSON, stderr="")

    analyzer = LocalAnalyzer(
        model="other-model", http_client=OllamaHttpClient(opener=opener), runner=runner
    )

    assert analyzer.analyze_frames([frame]).keywords == ("海",)
    assert calls and calls[0][1] == "run"


def test_ollama_http_error_is_an_analysis_failure_not_a_fallback():
    def opener(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":"model not found"}')
        )

    client = OllamaHttpClient(opener=opener)

    with pytest.raises(AnalysisError, match="HTTP 404"):
        client.generate("missing", "prompt", (), timeout=5, disable_thinking=False)
    with pytest.raises(OllamaUnavailable):
        OllamaHttpClient(
            opener=lambda *_a, **_k: (_ for _ in ()).throw(ConnectionRefusedError())
        ).generate("m", "p", (), timeout=5, disable_thinking=False)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("", "http://127.0.0.1:11434"),
        ("0.0.0.0", "http://127.0.0.1:11434"),
        ("0.0.0.0:11500", "http://127.0.0.1:11500"),
        ("http://192.168.1.5:8080", "http://192.168.1.5:8080"),
    ],
)
def test_ollama_host_setting_becomes_a_client_address(host, expected):
    assert _ollama_base_url({"OLLAMA_HOST": host}) == expected


# --- previews and temporary frames --------------------------------------

def test_jpeg_previews_are_made_without_ffmpeg_and_discarded_after_use(tmp_path):
    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (2560, 1440), "navy").save(frame)
    preparer = FfmpegImagePreparer(
        output_root=tmp_path / "previews",
        runner=lambda *_a, **_k: pytest.fail("ffmpeg must not start for a JPEG"),
    )

    preview = preparer.prepare(frame)

    with Image.open(preview) as image:
        assert max(image.size) == 1024
    preparer.discard(frame)
    assert frame.is_file()
    preparer.discard(preview)
    assert not preview.exists()


# --- logs and the single window ------------------------------------------

def test_worker_output_is_appended_to_the_worker_log(tmp_path, monkeypatch):
    monkeypatch.setenv(app_logging.LOG_DIRECTORY_ENV, str(tmp_path / "logs"))
    process = supervisor_module._spawn_process(
        [sys.executable, "-c", "import sys; print('progress'); print('boom', file=sys.stderr)"]
    )
    process.wait(timeout=30)

    text = (tmp_path / "logs" / app_logging.WORKER_LOG).read_text(encoding="utf-8")

    assert "analysis worker" in text and "progress" in text and "boom" in text


def test_worker_log_rotates_when_it_grows(tmp_path, monkeypatch):
    monkeypatch.setenv(app_logging.LOG_DIRECTORY_ENV, str(tmp_path))
    log = tmp_path / app_logging.WORKER_LOG
    log.write_bytes(b"x" * (app_logging.MAX_BYTES + 1))

    handle = app_logging.open_worker_log("next run")
    handle.close()

    assert (tmp_path / f"{app_logging.WORKER_LOG}.1").stat().st_size > app_logging.MAX_BYTES
    assert log.stat().st_size < 100


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex")
def test_second_holder_of_a_mutex_is_told_it_already_exists():
    name = f"VideoLibraryOrganizer-Test-{os.getpid()}"

    assert hold(name) is True
    assert hold(name) is False


def test_installer_waits_for_the_mutex_the_program_holds():
    from media_catalog.single_instance import RUNNING_MUTEX

    script = (PROJECT / "packaging" / "MediaCatalogVideoDesktop.iss").read_text(encoding="utf-8")

    assert f"AppMutex={RUNNING_MUTEX}" in script
    assert "CloseApplications=yes" in script


# --- release documents ---------------------------------------------------

def test_version_wording_for_documents_and_tags():
    assert release_docs.version_label("0.3.0b7") == "0.3.0 Beta 7"
    assert release_docs.version_tag("0.3.0b7") == "0.3.0-beta.7"
    assert release_docs.version_label("1.0.0") == release_docs.version_tag("1.0.0") == "1.0.0"


def test_shipped_documents_name_the_project_version():
    assert release_docs.stale_documents() == []


def test_tester_notes_carry_the_installer_hash(tmp_path):
    setup = tmp_path / "VideoLibraryOrganizer-0.3.0-beta.7-Setup.exe"
    setup.write_bytes(b"installer")

    notes = release_docs.tester_notes(setup, "0.3.0b7")

    assert "0.3.0 Beta 7" in notes and setup.name in notes
    assert hashlib.sha256(b"installer").hexdigest().upper() in notes
    assert "{{" not in notes


# --- signing helper under CI ----------------------------------------------

def test_powershell_child_does_not_inherit_a_pwsh7_module_path():
    import codesign

    env = codesign._powershell_environment(
        {"PSModulePath": r"C:\Program Files\PowerShell\7\Modules", "Path": "x", "SystemRoot": "C:"}
    )

    assert "PSModulePath" not in env and env["Path"] == "x"
    assert "psmodulepath" not in {key.lower() for key in codesign._powershell_environment({"psmodulepath": "y"})}


# --- version shown in the window -------------------------------------------

def test_version_shown_in_the_window_matches_the_project():
    from media_catalog import __version__
    from media_catalog._version import display_version

    assert __version__ == release_docs.project_version()
    assert display_version(__version__) == release_docs.version_label(__version__)
    assert display_version("0.3.0b8") == "0.3.0 Beta 8" and display_version("0.3.0") == "0.3.0"
