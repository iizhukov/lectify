import asyncio
import os
import sys
import json
import subprocess

import pytest
from templates import env


@pytest.mark.parametrize('command', ['python -m agent', [], [''], {'command':'agent'}])
def test_supervised_entrypoint_rejects_non_argv_command(tmp_path, command):
    from config.plugin_models import PluginConfig, PluginManifest
    from generators.runner import run_plugin
    run_plugin(PluginManifest(plugin=PluginConfig(name='supervised_test')), tmp_path/'generated')
    source = tmp_path/'src'
    source.mkdir()
    (source/'plugin.py').write_text('class PluginHandler: pass\n')
    result = subprocess.run([sys.executable,'-m','generated.main'], cwd=tmp_path,
        env=dict(os.environ, PLUGIN_MODE='supervised', LECTIFY_AGENT_COMMAND_JSON=json.dumps(command)),
        capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'trusted agent command argument vector is required' in result.stderr


def supervisor():
    namespace = {}
    exec(compile(env.get_template('services/process_supervisor.py.j2').render(), '<supervisor>', 'exec'), namespace)
    return namespace['run_pair']


def command(path):
    return [sys.executable, '-c',
        'import os,time;from pathlib import Path;Path('+repr(str(path))+').write_text(str(os.getpid()));time.sleep(60)']


async def ready(paths):
    async with asyncio.timeout(5):
        while not all(path.exists() for path in paths):
            await asyncio.sleep(0.01)


def assert_reaped(paths):
    for path in paths:
        with pytest.raises(ProcessLookupError):
            os.kill(int(path.read_text()), 0)


@pytest.mark.asyncio
async def test_pair_stops_both_processes_after_work(tmp_path):
    paths = [tmp_path / 'agent', tmp_path / 'plugin']
    async def work():
        await ready(paths)
        return 42
    assert await supervisor()(*(command(path) for path in paths), work) == 42
    assert_reaped(paths)


@pytest.mark.asyncio
async def test_pair_cancellation_reaps_both_processes(tmp_path):
    paths = [tmp_path / 'agent', tmp_path / 'plugin']
    async def work():
        await asyncio.Event().wait()
    task = asyncio.create_task(supervisor()(*(command(path) for path in paths), work))
    await ready(paths)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_reaped(paths)


@pytest.mark.asyncio
async def test_early_exit_fails_assignment(tmp_path):
    async def work():
        await asyncio.Event().wait()
    with pytest.raises(RuntimeError, match='exited before'):
        await supervisor()([sys.executable,'-c','raise SystemExit(0)'], command(tmp_path/'plugin'), work)


@pytest.mark.asyncio
async def test_term_resistant_descendant_is_stopped_with_its_group(tmp_path):
    import signal
    descendant_pid, heartbeat = tmp_path/'descendant.pid', tmp_path/'heartbeat'
    child = (
        'import os,signal,time;from pathlib import Path;'
        'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
        f'Path({str(descendant_pid)!r}).write_text(str(os.getpid()));'
        f'path=Path({str(heartbeat)!r});'
        '\nwhile True:\n path.write_text(str(time.monotonic_ns()));time.sleep(0.01)'
    )
    leader = [sys.executable,'-c',
        'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(child)+']);time.sleep(60)']
    async def work():
        await ready([descendant_pid, heartbeat])
    try:
        await supervisor()(command(tmp_path/'agent'), leader, work)
        await asyncio.sleep(0.05)
        stopped = heartbeat.read_text()
        await asyncio.sleep(0.1)
        assert heartbeat.read_text() == stopped
    finally:
        if descendant_pid.exists():
            try:
                os.kill(int(descendant_pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
