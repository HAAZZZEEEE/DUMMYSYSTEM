# CLI 命令参考

由命令声明生成；使用 scripts/command_reference.py --check 核对。

全局参数：`--workspace`、`--config`、`--json`、`--actor`、`--request-id`、`--if-version`、`--trace-id`

退出码：0 成功；1 检查发现问题；2 参数、状态或执行错误。

## dmy capabilities

- `--command`：可选；类型 str
- `--action`：可选；类型 str

## dmy doctor

- `--full`：可选；类型 bool；默认 false

## dmy check

- `--docs`：可选；类型 bool；默认 false

## dmy init


## dmy context

- `--task`：必填；类型 str
- `--section`：可选；类型 str；取值 all, reading, repositories, summary；默认 "all"

## dmy stats

- `--days`：可选；类型 int

## dmy diagnose show

- `id`：必填；类型 str

## dmy governance relocate

- `--project`：必填；类型 str
- `--reason`：必填；类型 str
- `--dry-run`：可选；类型 bool；默认 false
- `--if-plan`：可选；类型 str
- `--section`：必填；类型 str；取值 entry, system, templates

## dmy governance rollback

- `--project`：必填；类型 str
- `--reason`：必填；类型 str
- `--dry-run`：可选；类型 bool；默认 false
- `--if-plan`：可选；类型 str
- `--operation`：必填；类型 str

## dmy project list

- `--include-archived`：可选；类型 bool；默认 false
- `--include-deleted`：可选；类型 bool；默认 false

## dmy project show

- `id`：必填；类型 str

## dmy project create

- `--title`：必填；类型 str
- `--created`：可选；类型 str

## dmy project update

- `--project`：必填；类型 str
- `--title`：可选；类型 str
- `--aliases`：可选；类型 str
- `--description`：可选；类型 str

## dmy project pause

- `--project`：必填；类型 str
- `--reason`：必填；类型 str

## dmy project resume

- `--project`：必填；类型 str
- `--reason`：必填；类型 str

## dmy project rename

- `--project`：必填；类型 str
- `--title`：必填；类型 str
- `--reason`：必填；类型 str
- `--dry-run`：可选；类型 bool；默认 false
- `--if-plan`：可选；类型 str

## dmy project archive

- `--project`：必填；类型 str
- `--reason`：必填；类型 str
- `--dry-run`：可选；类型 bool；默认 false
- `--if-plan`：可选；类型 str
- `--allow-unfinished`：可选；类型 bool；默认 false

## dmy project unarchive

- `--project`：必填；类型 str
- `--reason`：必填；类型 str
- `--dry-run`：可选；类型 bool；默认 false
- `--if-plan`：可选；类型 str

## dmy project delete

- `--project`：必填；类型 str
- `--reason`：必填；类型 str

## dmy project undelete

- `--project`：必填；类型 str
- `--reason`：必填；类型 str

## dmy project sync

- `--project`：可选；类型 str
- `--apply`：可选；类型 bool；默认 false

## dmy task list

- `--project`：可选；类型 str
- `--include-archived`：可选；类型 bool；默认 false
- `--include-deleted`：可选；类型 bool；默认 false

## dmy task show

- `id`：必填；类型 str

## dmy task create

- `--project`：可选；类型 str
- `--title`：必填；类型 str
- `--origin`：必填；类型 str
- `--goal`：必填；类型 str
- `--owner`：可选；类型 str
- `--requires-acceptance`：可选；类型 bool；默认 false
- `--read-path`：可选；类型 str
- `--write-path`：可选；类型 str

## dmy task update

- `--task`：必填；类型 str
- `--note`：必填；类型 str
- `--status`：可选；类型 str；取值 active, awaiting_acceptance, blocked, cancelled, completed
- `--owner`：可选；类型 str
- `--accepted`：可选；类型 bool；默认 false
- `--title`：可选；类型 str
- `--goal`：可选；类型 str
- `--read-path`：可选；类型 str
- `--write-path`：可选；类型 str
- `--remote-resources`：可选；类型 str
- `--clear-read-paths`：可选；类型 bool；默认 false
- `--clear-write-paths`：可选；类型 bool；默认 false

## dmy task handoff

- `--task`：必填；类型 str
- `--note`：必填；类型 str
- `--status`：可选；类型 str；取值 active, awaiting_acceptance, blocked, cancelled, completed
- `--owner`：必填；类型 str
- `--accepted`：可选；类型 bool；默认 false
- `--authorization`：可选；类型 str

## dmy task rename

- `--task`：必填；类型 str
- `--title`：必填；类型 str
- `--reason`：必填；类型 str
- `--dry-run`：可选；类型 bool；默认 false
- `--if-plan`：可选；类型 str

## dmy task move

- `--task`：必填；类型 str
- `--to-project`：必填；类型 str
- `--reason`：必填；类型 str
- `--authorization`：可选；类型 str
- `--dry-run`：可选；类型 bool；默认 false
- `--if-plan`：可选；类型 str

## dmy task archive

- `--task`：必填；类型 str
- `--reason`：必填；类型 str
- `--dry-run`：可选；类型 bool；默认 false
- `--if-plan`：可选；类型 str
- `--allow-unfinished`：可选；类型 bool；默认 false

## dmy task unarchive

- `--task`：必填；类型 str
- `--reason`：必填；类型 str
- `--dry-run`：可选；类型 bool；默认 false
- `--if-plan`：可选；类型 str

## dmy task delete

- `--task`：必填；类型 str
- `--reason`：必填；类型 str

## dmy task undelete

- `--task`：必填；类型 str
- `--reason`：必填；类型 str

## dmy run list

- `--task`：必填；类型 str

## dmy run show

- `id`：必填；类型 str
- `--task`：必填；类型 str

## dmy run create

- `--task`：必填；类型 str
- `--title`：必填；类型 str
- `--host`：必填；类型 str
- `--source`：必填；类型 str
- `--inputs`：必填；类型 str
- `--command`：必填；类型 str
- `--retry-of`：可选；类型 str

## dmy run start

- `--task`：必填；类型 str
- `--run`：必填；类型 str

## dmy run finish

- `--task`：必填；类型 str
- `--run`：必填；类型 str
- `--authorization`：可选；类型 str
- `--status`：必填；类型 str；取值 completed, failed, cancelled
- `--result`：必填；类型 str
- `--exit-code`：可选；类型 int
- `--evidence`：可选；类型 str；默认 []

## dmy run update

- `--task`：必填；类型 str
- `--run`：必填；类型 str
- `--status`：可选；类型 str；取值 cancelled, completed, failed, planned, running
- `--host`：可选；类型 str
- `--source`：可选；类型 str
- `--inputs`：可选；类型 str
- `--command`：可选；类型 str
- `--result`：可选；类型 str
- `--exit-code`：可选；类型 int
- `--add-evidence`：可选；类型 str；默认 []

## dmy run rename

- `--task`：必填；类型 str
- `--run`：必填；类型 str
- `--title`：必填；类型 str

## dmy run archive

- `--task`：必填；类型 str
- `--run`：必填；类型 str
- `--reason`：必填；类型 str

## dmy run unarchive

- `--task`：必填；类型 str
- `--run`：必填；类型 str
- `--reason`：必填；类型 str

## dmy run delete

- `--task`：必填；类型 str
- `--run`：必填；类型 str
- `--reason`：必填；类型 str

## dmy run undelete

- `--task`：必填；类型 str
- `--run`：必填；类型 str
- `--reason`：必填；类型 str

## dmy repo list


## dmy repo show

- `id`：必填；类型 str

## dmy repo register

- `--repo`：必填；类型 str
- `--title`：必填；类型 str
- `--purpose`：必填；类型 str

## dmy repo bind

- `--repo`：必填；类型 str
- `--path`：必填；类型 str

## dmy repo link

- `--repo`：必填；类型 str
- `--task`：可选；类型 str
- `--project`：可选；类型 str
- `--subpath`：可选；类型 str

## dmy repo resolve

- `--task`：可选；类型 str
- `--project`：可选；类型 str

## dmy repo snapshot

- `--task`：必填；类型 str
- `--run`：必填；类型 str
- `--checkout`：可选；类型 str

## dmy scope check

- `--task`：必填；类型 str
- `--read-path`：可选；类型 str；默认 []
- `--write-path`：可选；类型 str；默认 []

## dmy operation list


## dmy operation show

- `id`：必填；类型 str

## dmy operation recover

- `id`：必填；类型 str
