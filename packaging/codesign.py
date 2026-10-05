"""Authenticode signing for release builds.

Smart App Control blocks unsigned code, and it checks every executable file a
program loads, not only the installer. A release therefore signs each .exe,
.dll and .pyd that is not already validly signed by someone else (Python's
own DLLs, Microsoft runtimes), the viewer's files before PyInstaller packs
them into its single exe, and the installer and uninstaller.

Signing is optional: with nothing configured, builds stay unsigned and say
so. Configure exactly one certificate source through the environment:

  VLO_SIGN_THUMBPRINT    SHA-1 thumbprint of a code signing certificate in
                         CurrentUser\\My or LocalMachine\\My (a USB token or a
                         cloud signing service usually installs it there)
  VLO_SIGN_PFX           a .pfx file, with VLO_SIGN_PFX_PASSWORD if it has one
  VLO_SIGNTOOL_ARGS      signtool.exe arguments that pick the certificate,
                         used as given (e.g. Microsoft Artifact Signing:
                         /dlib <Azure.CodeSigning.Dlib.dll> /dmdf <metadata.json>)

Optional: VLO_SIGNTOOL (signtool.exe path; required with VLO_SIGNTOOL_ARGS),
VLO_TIMESTAMP_URL (RFC 3161 server, default below) and VLO_SIGN_REQUIRED=1
(fail the build when anything is left unsigned).

Usage: python codesign.py sign <file or folder>...
       python codesign.py verify [--require] <file or folder>...
       python codesign.py status
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

PE_SUFFIXES = {".exe", ".dll", ".pyd"}
DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"
_BATCH = 40
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def configured(env=os.environ) -> bool:
    return bool(env.get("VLO_SIGN_THUMBPRINT") or env.get("VLO_SIGN_PFX") or env.get("VLO_SIGNTOOL_ARGS"))


def required(env=os.environ) -> bool:
    return env.get("VLO_SIGN_REQUIRED", "").strip() in {"1", "true", "yes"}


def describe(env=os.environ) -> str:
    if env.get("VLO_SIGNTOOL_ARGS"):
        return "signtool with VLO_SIGNTOOL_ARGS"
    if env.get("VLO_SIGN_THUMBPRINT"):
        return f"certificate {env['VLO_SIGN_THUMBPRINT'][:8]}... from the Windows certificate store"
    if env.get("VLO_SIGN_PFX"):
        return f"certificate file {Path(env['VLO_SIGN_PFX']).name}"
    return "not configured"


def pe_files(paths) -> list[Path]:
    found: list[Path] = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            found += sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in PE_SUFFIXES)
        elif path.is_file() and (path.suffix.lower() in PE_SUFFIXES or _is_pe(path)):
            # A file named explicitly may carry any extension (Inno Setup
            # hands over its uninstaller as a temporary file).
            found.append(path)
    return found


def _is_pe(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(2) == b"MZ"


def _powershell(script: str, payload: dict) -> list[dict]:
    """Run a Windows PowerShell snippet that reads a JSON payload and prints JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "payload.json"
        data.write_text(json.dumps(payload), encoding="utf-8")
        program = Path(tmp) / "run.ps1"
        program.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            f"$payload = Get-Content -LiteralPath '{data}' -Raw -Encoding UTF8 | ConvertFrom-Json\n"
            + script,
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(program)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell signing step failed: {result.stderr.strip()[-800:]}")
    text = result.stdout.strip()
    rows = json.loads(text) if text else []
    return rows if isinstance(rows, list) else [rows]


_STATUS_SCRIPT = r"""
$rows = foreach ($f in $payload.files) {
  $s = Get-AuthenticodeSignature -LiteralPath $f
  [pscustomobject]@{ path = $f; status = [string]$s.Status;
    signer = $(if ($s.SignerCertificate) { $s.SignerCertificate.Thumbprint } else { $null }) }
}
@($rows) | ConvertTo-Json -Compress -Depth 3
"""


def signature_status(files) -> dict[Path, dict]:
    """Status and signer thumbprint for each file ('NotSigned', 'Valid', ...)."""
    files = [str(Path(f)) for f in files]
    out: dict[Path, dict] = {}
    for start in range(0, len(files), 200):
        for row in _powershell(_STATUS_SCRIPT, {"files": files[start:start + 200]}):
            out[Path(row["path"])] = row
    return out


_SIGN_SCRIPT = r"""
if ($payload.pfx) {
  $flags = [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::DefaultKeySet
  $cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($payload.pfx, [string]$payload.password, $flags)
} else {
  $cert = @(Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My -CodeSigningCert |
            Where-Object Thumbprint -eq $payload.thumbprint) | Select-Object -First 1
  if (-not $cert) { throw "No code signing certificate with thumbprint $($payload.thumbprint) (with its private key) in CurrentUser\My or LocalMachine\My" }
}
$rows = foreach ($f in $payload.files) {
  $r = Set-AuthenticodeSignature -LiteralPath $f -Certificate $cert -HashAlgorithm SHA256 -TimestampServer $payload.timestamp
  [pscustomobject]@{ path = $f; status = [string]$r.Status; message = $r.StatusMessage;
    signer = $(if ($r.SignerCertificate) { $r.SignerCertificate.Thumbprint } else { $null }) }
}
@($rows) | ConvertTo-Json -Compress -Depth 3
"""


def drop_dangling_certificate(path) -> bool:
    """Clear a certificate-table entry that points past the end of the file.

    Some redistributed DLLs (Tcl/Tk from standalone Python builds) had their
    signature cut off but kept the entry pointing at it, and Windows refuses
    to sign such a file. The entry references nothing, so clearing it leaves
    the code untouched. Only ever called on copies being packaged.
    """
    path = Path(path)
    if not path.is_file():
        return False
    with path.open("r+b") as handle:
        data = handle.read(4096)
        if data[:2] != b"MZ":
            return False
        pe = int.from_bytes(data[0x3C:0x40], "little")
        if data[pe:pe + 4] != b"PE\0\0":
            return False
        optional = pe + 24
        magic = int.from_bytes(data[optional:optional + 2], "little")
        entry = optional + (112 if magic == 0x20B else 96) + 4 * 8  # IMAGE_DIRECTORY_ENTRY_SECURITY
        offset = int.from_bytes(data[entry:entry + 4], "little")
        size = int.from_bytes(data[entry + 4:entry + 8], "little")
        if not size or offset + size <= path.stat().st_size:
            return False
        handle.seek(entry)
        handle.write(b"\0" * 8)
    return True


def _signtool(env) -> str:
    tool = env.get("VLO_SIGNTOOL") or shutil.which("signtool")
    if not tool:
        raise RuntimeError("VLO_SIGNTOOL_ARGS is set but signtool.exe was not found; set VLO_SIGNTOOL to its path")
    return tool


def sign(files, env=os.environ) -> list[Path]:
    """Sign every given PE file that is not validly signed yet; returns those signed."""
    if not configured(env):
        return []
    status = signature_status(files)
    todo = [str(p) for p, row in status.items() if row["status"] == "NotSigned"]
    for path in todo:
        drop_dangling_certificate(path)
    timestamp = env.get("VLO_TIMESTAMP_URL") or DEFAULT_TIMESTAMP_URL
    for start in range(0, len(todo), _BATCH):
        batch = todo[start:start + _BATCH]
        if env.get("VLO_SIGNTOOL_ARGS"):
            command = [_signtool(env), "sign", "/fd", "SHA256", "/tr", timestamp, "/td", "SHA256",
                       *shlex.split(env["VLO_SIGNTOOL_ARGS"], posix=False), *batch]
            result = subprocess.run(command, capture_output=True, text=True, errors="replace", creationflags=_NO_WINDOW)
            if result.returncode != 0:
                raise RuntimeError(f"signtool failed: {(result.stdout + result.stderr).strip()[-800:]}")
            continue
        rows = _powershell(_SIGN_SCRIPT, {
            "files": batch, "timestamp": timestamp,
            "thumbprint": (env.get("VLO_SIGN_THUMBPRINT") or "").replace(" ", "").upper(),
            "pfx": env.get("VLO_SIGN_PFX") or "", "password": env.get("VLO_SIGN_PFX_PASSWORD") or "",
        })
        failed = [r for r in rows if not r.get("signer")]
        if failed:
            raise RuntimeError("Signing failed: " + "; ".join(f"{Path(r['path']).name}: {r.get('message')}" for r in failed[:5]))
    return [Path(p) for p in todo]


def signed_toc(entries, workdir, env=os.environ):
    """PyInstaller hook: sign copies of the binaries a one-file exe will unpack.

    `entries` is Analysis.binaries ((dest_name, src_path, typecode) tuples);
    returns the same list with unsigned PE sources replaced by signed copies.
    """
    if not configured(env):
        return entries
    workdir = Path(workdir)
    copies: dict[str, Path] = {}
    for dest, src, _kind in entries:
        if Path(src).suffix.lower() in PE_SUFFIXES and Path(src).is_file():
            target = workdir / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copies[src] = target
    sign(list(copies.values()), env)
    return [(dest, str(copies.get(src, src)), kind) for dest, src, kind in entries]


def unsigned(files) -> list[tuple[Path, str]]:
    return [(path, row["status"]) for path, row in signature_status(files).items() if row["status"] == "NotSigned"]


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"sign", "verify", "status"}:
        print(__doc__)
        return 2
    command, rest = args[0], args[1:]
    if command == "status":
        print(f"code signing: {describe()}")
        return 0
    require = "--require" in rest or required()
    targets = pe_files(r for r in rest if r != "--require")
    if command == "sign":
        if not configured():
            print("code signing: not configured - files stay unsigned (see packaging/codesign.py)")
            return 1 if required() else 0
        done = sign(targets)
        print(f"code signing: signed {len(done)} of {len(targets)} files ({describe()})")
        return 0
    left = unsigned(targets)
    print(f"code signing check: {len(targets) - len(left)} of {len(targets)} executable files signed")
    for path, _status in left[:20]:
        print(f"  unsigned: {path}")
    if len(left) > 20:
        print(f"  ... and {len(left) - 20} more")
    return 1 if (left and require) else 0


if __name__ == "__main__":
    raise SystemExit(main())
