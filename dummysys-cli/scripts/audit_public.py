"""只报告规则与位置的脱敏检查；私有拒绝词表由外部 JSON 提供。"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

SECRET = re.compile(r"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{30,}|AKIA[0-9A-Z]{16})")
LOCAL = re.compile(r"(?i)(?:[a-z]:[/\\]+(?:users|home)[/\\]+|/(?:home|Users)/)")
IP = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
INTERNAL = re.compile(r"(?i)(?:https?://[^\s/'\"]+\.(?:internal|intranet|corp)(?:[/:]|$)|https?://[^/@\s]+:[^/@\s]+@)")
FORBIDDEN = {".git", ".venv", "__pycache__", "runtime", "node_modules"}
ALLOWED_SUFFIXES = {".py",".md",".txt",".json",".toml",".js",".css",".html",".lock",".svg",".spec"}


def source_entries(root, git_history):
    """仅在明确检查 Git 对象时跳过根元数据；嵌套仓库仍被拒绝。"""
    for directory, dirs, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in list(dirs):
            path = parent / name
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                yield path
                dirs.remove(name)
            elif git_history and parent == root and name == ".git":
                dirs.remove(name)
        for name in files:
            yield parent / name


def git_entries(root):
    """检查本地全部 Git 对象，包括不可达提交；不执行仓库中的任何钩子。"""
    def git(*arguments):
        process = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True)
        if process.returncode:
            raise ValueError("Git 对象读取失败；检查仓库完整性，原始错误不写入公开报告")
        return process.stdout

    metadata = root / ".git"
    if not metadata.is_dir() or metadata.is_symlink() or (hasattr(metadata, "is_junction") and metadata.is_junction()):
        raise ValueError("--git-history 要求根目录自身包含普通 .git 目录")
    if Path(os.fsdecode(git("rev-parse", "--show-toplevel")).strip()).resolve() != root:
        raise ValueError("--source 必须为实际 Git 根目录")
    objects = [line.split() for line in git("cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype)").decode("ascii").splitlines()]
    names = {}
    for oid, kind in objects:
        if kind != "commit":
            continue
        for entry in git("ls-tree", "-rz", "--full-tree", oid).split(b"\0"):
            if not entry:
                continue
            attributes, raw_name = entry.split(b"\t", 1)
            mode, _, blob = attributes.decode("ascii").split()
            name = raw_name.decode("utf-8")
            names.setdefault(blob, set()).add(name)
            if mode not in ("100644", "100755") or set(Path(name).parts) & FORBIDDEN or (Path(name).suffix not in ALLOWED_SUFFIXES and Path(name).name != ".gitignore"):
                yield f"git:{oid}/{name}", b"", None, "unexpected_git_entry"
    for oid, kind in objects:
        if kind not in ("blob", "commit", "tag"):
            continue
        data = git("cat-file", kind, oid)
        if kind == "blob":
            paths = sorted(names.get(oid, []))
            for name in paths or [None]:
                yield f"git:{oid}/{name or 'unmapped-blob'}", data, name, None if name else "unmapped_git_blob"
        else:
            yield f"git:{oid}/{kind}", data, None, None
    for name in ("config", "HEAD", "packed-refs"):
        path = metadata / name
        if path.is_file():
            yield f"git-local/{name}", path.read_bytes(), None, None
    for path in sorted((metadata / "logs").rglob("*")):
        if path.is_file():
            yield "git-local/" + path.relative_to(metadata).as_posix(), path.read_bytes(), None, None


def inspect(name, data, deny):
    text = data.decode("utf-8", errors="ignore")
    findings = []
    for code, regex in (("private_home_path", LOCAL), ("credential_shape", SECRET), ("internal_service", INTERNAL)):
        for match in regex.finditer(text):
            findings.append(dict(path=name, line=text.count("\n", 0, match.start()) + 1, rule=code))
    for token in deny:
        # Include JSON-escaped and slash-normalized representations without echoing them.
        variants = {token, token.replace("\\", "/"), json.dumps(token, ensure_ascii=False)[1:-1]}
        if any(v and v.lower() in text.lower() for v in variants):
            findings.append(dict(path=name, rule="private_deny_token", token_hash=hashlib.sha256(token.encode()).hexdigest()[:12]))
    for match in IP.finditer(text):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified or any(address in ipaddress.ip_network(n) for n in ("192.0.2.0/24","198.51.100.0/24","203.0.113.0/24")):
            continue
        if address.is_private:
            findings.append(dict(path=name, line=text.count("\n",0,match.start())+1, rule="private_network_address"))
    return findings


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--wheels", type=Path)
    parser.add_argument("--deny-file", type=Path, required=True, help="外部 JSON 字符串数组，报告不回显原文")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--reviewed", type=Path, help="人工复核的精确位置、文件哈希与理由；文件变化则失效")
    parser.add_argument("--git-history", action="store_true", help="允许根 .git，并检查全部 Git 对象、提交身份及本地配置/引用日志")
    args=parser.parse_args(argv)
    root=args.source.resolve()
    deny=json.loads(args.deny_file.read_text(encoding="utf-8"))
    if not isinstance(deny,list) or not all(isinstance(t,str) and t for t in deny):
        parser.error("拒绝词表必须是非空字符串的数组")
    findings=[]; hashes={}; wheels={}; count=0; history={}; review_paths={}
    for p in sorted(source_entries(root, args.git_history)):
        if p.is_symlink() or (hasattr(p,"is_junction") and p.is_junction()):
            findings.append(dict(path=p.relative_to(root).as_posix(),rule="source_link")); continue
        if not p.is_file(): continue
        relative=p.relative_to(root)
        if set(relative.parts) & FORBIDDEN or (p.suffix not in ALLOWED_SUFFIXES and p.name != ".gitignore"):
            findings.append(dict(path=relative.as_posix(),rule="unexpected_source_file"))
        data=p.read_bytes();name=relative.as_posix();hashes[name]=hashlib.sha256(data).hexdigest()
        findings.extend(inspect(name,data,deny));count+=1
    if args.git_history:
        try:
            for name, data, original, problem in git_entries(root):
                history[name]=hashlib.sha256(data).hexdigest()
                if original:
                    review_paths[name]=original
                if problem:
                    findings.append(dict(path=name,rule=problem))
                findings.extend(inspect(name,data,deny));count+=1
        except (OSError, ValueError, UnicodeError):
            findings.append(dict(rule="git_history_unavailable"))
    if args.wheels:
        for p in sorted(args.wheels.glob("dummysys_*.whl")):
            wheels[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
            with zipfile.ZipFile(p) as archive:
                for name in archive.namelist():
                    if name.endswith("/"):continue
                    if name.endswith((".pyc",".pyo")):findings.append(dict(path=p.name+"!"+name,rule="compiled_source"))
                    findings.extend(inspect(p.name+"!"+name,archive.read(name),deny));count+=1
        if len(wheels)!=3:findings.append(dict(rule="expected_three_project_wheels"))
    reviewed=[]
    decisions=json.loads(args.reviewed.read_text(encoding='utf-8')) if args.reviewed else []
    unresolved=[]
    for finding in findings:
        name=finding.get('path')
        file_hash=hashes.get(name) or history.get(name)
        decision=next((d for d in decisions if d.get('path')==review_paths.get(name,name) and d.get('line')==finding.get('line')
                       and d.get('rule')==finding.get('rule') and d.get('sha256')==file_hash and d.get('reason')),None)
        if decision:
            reviewed.append(dict(**finding,reason=decision['reason'],sha256=file_hash))
        else:
            unresolved.append(finding)
    result=dict(schema_version=1,ok=not unresolved,scanned_files=count,unresolved=unresolved,reviewed=reviewed,
                source_sha256=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),
                source_files=hashes,wheels=wheels,git_entries=history,
                coverage="源码全部文件（含隐藏文件）、三份业务 wheel；外部拒绝词、个人主目录、内网地址与凭据形态。依赖 wheel 保持上游分发，另记构建哈希。自动扫描之外仍需发布前人工权利审查。")
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(dict(ok=result["ok"],scanned_files=count,unresolved_count=len(unresolved),reviewed_count=len(reviewed),report=str(args.report)),ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__=="__main__":
    raise SystemExit(main())
