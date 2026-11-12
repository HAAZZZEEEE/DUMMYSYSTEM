"""构建与安装子进程的环境边界；不继承 pip 的目标或依赖来源。"""
import os


def packaging_environment(runtime):
    excluded = {'PYTHONPATH', 'PYTHONHOME', 'DMY_CONFIG', 'DMY_EXE'}
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith('PIP_') and key.upper() not in excluded}
    env.update(PIP_CONFIG_FILE=os.devnull, PIP_CACHE_DIR=str(runtime / 'cache/pip'),
               PIP_NO_INPUT='1', TEMP=str(runtime / 'tmp'), TMP=str(runtime / 'tmp'), TMPDIR=str(runtime / 'tmp'),
               PYTHONDONTWRITEBYTECODE='1')
    return env


def venv_python(environment):
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
