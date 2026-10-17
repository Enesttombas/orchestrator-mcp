"""Install a backed-up launcher and scoped MCP configuration. No worker daemon changes."""
import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from store import Store


def install():
    canonical=Path(__file__).resolve().parent
    config=Path(os.environ.get('ORCHESTRATOR_MCP_CONFIG',str(Path.home()/'.gemini/config/mcp_config.json')))
    settings=json.loads(config.read_text(encoding='utf-8'))
    target=Path.home()/'.orchestrator/mcp_servers/orchestrator/server.py'
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup=target.parent/'backups'/stamp
    backup.mkdir(parents=True)
    shutil.copy2(config,backup/'mcp_config.json')
    if target.exists():shutil.copy2(target,backup/'server.py')
    entry=settings['mcpServers']['orchestrator']
    env=entry.setdefault('env',{})
    dbpath=Path(env.get('ORCHESTRATOR_DB_PATH',str(Path.home()/'.orchestrator/orchestrator.db')))
    before=0
    if dbpath.exists():
        with sqlite3.connect(dbpath) as source,sqlite3.connect(backup/'orchestrator.db') as dest:
            source.backup(dest)
            before=source.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
    migrated=Store(dbpath)
    with migrated.tx() as c:after=c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
    assert before==after,'Migration changed historical session count'
    launcher=('"""Installed launcher; implementation and tests live in the orchestrator-mcp checkout."""\n'
              'import runpy\nimport sys\n'
              f'sys.path.insert(0,{str(canonical)!r})\n'
              f'if __name__ == "__main__":\n    runpy.run_path({str(canonical/"server.py")!r},run_name="__main__")\n')
    entry['command']=sys.executable
    entry['args']=['-X','utf8',str(target)]
    env.update(ORCHESTRATOR_GEMINI_ENABLED='1',PYTHONIOENCODING='utf-8')
    try:
        temporary=target.with_suffix('.tmp');temporary.write_text(launcher,encoding='utf-8')
        os.replace(temporary,target)
        temporary=config.with_suffix('.tmp');temporary.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,config)
    except BaseException:
        shutil.copy2(backup/'mcp_config.json',config)
        if (backup/'server.py').exists():shutil.copy2(backup/'server.py',target)
        raise
    return {'entry':str(target),'canonical':str(canonical),'backup':str(backup),
            'historical_sessions_preserved':after,'scoped_execution_enabled':True}


if __name__=='__main__':print(json.dumps(install(),ensure_ascii=False,indent=2))
