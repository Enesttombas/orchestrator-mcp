"""Read/refresh installed MCP health; never creates tasks or makes model calls."""
import argparse
import json
from pathlib import Path
import time

from test_orchestrator import Wire


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    config=json.loads((Path.home()/'.gemini/config/mcp_config.json').read_text(encoding='utf-8'))['mcpServers']['orchestrator']
    wire=Wire(args.output.resolve().parent,entry=Path(config['args'][-1]),env_overrides=config['env'])
    try:
        names=sorted(t['name'] for t in wire.request('tools/list',{})['result']['tools'])
        quotas=wire.call('orchestrator_refresh_quotas')['accounts']
        health=wire.call('orchestrator_pool_status')
        sessions=wire.call('orchestrator_list_sessions',limit=10)
        good=sum(q['fraction'] is not None and not q['error'] for q in quotas)
        result={'checked_at':time.time(),'tools':names,'quota_readable':good,'accounts':health['accounts'],
                'refreshed_quotas':quotas,
                'execution_enabled':health['enabled'],'model':health['model'],
                'historical_sessions':len(sessions)}
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'tools':len(names),'quota_readable':good,'enabled':health['enabled'],
                          'historical_sessions':len(sessions),'output':str(args.output)}))
        assert len(names)==18 and good==15 and health['enabled']
    finally:wire.close()


if __name__=='__main__':main()
