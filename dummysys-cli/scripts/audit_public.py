"""只报告规则与位置的脱敏检查；私有拒绝词表由外部 JSON 提供。"""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import zipfile
from urllib.parse import urlsplit

SECRET = re.compile(r"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{30,}|AKIA[0-9A-Z]{16})")
LOCAL = re.compile(r"(?i)(?:[a-z]:[/\\]+(?:users|home)[/\\]+|/(?:home|Users)/)")
IP = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
INTERNAL = re.compile(r"(?i)(?:https?://[^\s/'\"]+\.(?:internal|intranet|corp)(?:[/:]|$)|https?://[^/@\s]+:[^/@\s]+@)")
FORBIDDEN = {".git", ".venv", "__pycache__", "runtime", "node_modules"}
ALLOWED_SUFFIXES = {".py",".md",".txt",".json",".toml",".js",".css",".html",".lock",".svg",".spec"}


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
    args=parser.parse_args(argv)
    root=args.source.resolve()
    deny=json.loads(args.deny_file.read_text(encoding="utf-8"))
    if not isinstance(deny,list) or not all(isinstance(t,str) and t for t in deny):
        parser.error("拒绝词表必须是非空字符串的数组")
    findings=[]; hashes={}; wheels={}; count=0
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or (hasattr(p,"is_junction") and p.is_junction()):
            findings.append(dict(path=p.relative_to(root).as_posix(),rule="source_link")); continue
        if not p.is_file(): continue
        relative=p.relative_to(root)
        if set(relative.parts) & FORBIDDEN or (p.suffix not in ALLOWED_SUFFIXES and p.name != ".gitignore"):
            findings.append(dict(path=relative.as_posix(),rule="unexpected_source_file"))
        data=p.read_bytes();name=relative.as_posix();hashes[name]=hashlib.sha256(data).hexdigest()
        findings.extend(inspect(name,data,deny));count+=1
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
        decision=next((d for d in decisions if d.get('path')==finding.get('path') and d.get('line')==finding.get('line')
                       and d.get('rule')==finding.get('rule') and d.get('sha256')==hashes.get(finding.get('path')) and d.get('reason')),None)
        if decision:
            reviewed.append(dict(**finding,reason=decision['reason'],sha256=decision['sha256']))
        else:
            unresolved.append(finding)
    result=dict(schema_version=1,ok=not unresolved,scanned_files=count,unresolved=unresolved,reviewed=reviewed,
                source_sha256=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),
                source_files=hashes,wheels=wheels,
                coverage="源码全部文件（含隐藏文件）、三份业务 wheel；外部拒绝词、个人主目录、内网地址与凭据形态。依赖 wheel 保持上游分发，另记构建哈希。自动扫描之外仍需发布前人工权利审查。")
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(dict(ok=result["ok"],scanned_files=count,unresolved_count=len(unresolved),reviewed_count=len(reviewed),report=str(args.report)),ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__=="__main__":
    raise SystemExit(main())
