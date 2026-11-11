"""在新工作区演示 Project/Task/Run；只通过公开 CLI 管理结构。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--actor", required=True, help="本次演练的执行者标识")
    args = parser.parse_args()
    if not args.workspace.is_absolute():
        parser.error("--workspace 必须为绝对路径")
    workspace = args.workspace.resolve()

    def dmy(*command):
        process = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", "-B", "-m", "dummysys_cli",
             "--workspace", str(workspace), *map(str, command), "--json"],
            capture_output=True, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if process.returncode:
            raise RuntimeError(process.stdout or process.stderr)
        return json.loads(process.stdout)["data"]

    def write(*command, version=None):
        options = ["--actor", args.actor, "--request-id", str(uuid4())]
        if version is not None:
            options += ["--if-version", version]
        return dmy(*command, *options)["result"]

    projects = dmy("project", "list")
    if dmy("task", "list") or any(Path(p["document"]).parent.name != "00-Playground" for p in projects):
        raise ValueError("示例只写入新初始化的工作区；已有项目或 Task 时拒绝，请使用另一空工作区")
    locations = dmy("doctor")["locations"]
    project_id = write("project", "create", "--title", "入门演练")["project_id"]
    project = dmy("project", "show", project_id)
    documents = Path(project["document"]).parent
    resources = Path(locations["runtime_root"]) / "project_src" / project["name"]
    task_id = write("task", "create", "--project", project_id,
                    "--title", "统计示例数据", "--origin", "user", "--goal", "计算三项合成数据的数量与总和",
                    "--read-path", documents, "--write-path", documents, "--write-path", resources)["task_id"]
    run = write("run", "create", "--task", task_id, "--title", "首次统计",
                "--host", "local-example", "--source", "examples/first_project.py",
                "--inputs", "合成整数 2 3 5", "--command", "Python len 和 sum")
    run_id = run["run_id"]
    current = dmy("run", "show", run_id, "--task", task_id)
    write("run", "start", "--task", task_id, "--run", run_id, version=current["version"])

    # 普通结果文件按 Run 归属保存，结构和状态继续交给 CLI。
    numbers = [2, 3, 5]
    result_path = Path(run["record"]).parent / "result.json"
    with result_path.open("x", encoding="utf-8") as stream:
        json.dump(dict(inputs=numbers, count=len(numbers), total=sum(numbers)), stream, indent=2)
        stream.write("\n")
    current = dmy("run", "show", run_id, "--task", task_id)
    write("run", "finish", "--task", task_id, "--run", run_id, "--status", "completed",
          "--exit-code", "0", "--result", "已核对：3 项，总和 10；仅为合成演练",
          "--evidence", result_path, version=current["version"])

    task = dmy("task", "show", task_id)
    with Path(task["document"]).open("a", encoding="utf-8") as stream:
        stream.write("\n## 当前摘要\n\n三项合成数据统计完成：数量 3，总和 10。"
                     "\n\n下一步：演练项目导出与恢复；从 CLI context 的阅读入口按需查询本次 Run。"
                     "\n\n本次没有关联代码仓库或外部资源；不代表真实业务验证。\n")
    # 普通正文的修改也会改变 version，写结构前重新查询。
    task = dmy("task", "show", task_id)
    write("task", "update", "--task", task_id, "--note", "统计完成；下一步演练导出与恢复",
          version=task["version"])
    context = dmy("context", "--task", task_id, "--section", "reading")
    check = dmy("check")
    if not check["ok"]:
        raise RuntimeError("示例记录校验未通过")
    result = dict(workspace=str(workspace), project_id=project_id, task_id=task_id, run_id=run_id,
                  task_document=task["document"], evidence=str(result_path), context=context, check_ok=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print("示例未完成，已写内容保留。核对 CLI 错误与 Run；不要覆盖重跑：\n" + str(error), file=sys.stderr)
        raise SystemExit(1)

