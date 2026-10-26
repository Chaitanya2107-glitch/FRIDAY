"""Record owned-server startup diagnostics for the same frozen synthetic cases."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

from probe_dialogue_followups import ROOT, main
from providers.ollama import runtime as runtime_module


async def trace(args):
    original, started = runtime_module.subprocess.Popen, []
    with args.runtime_log.open('w', encoding='utf-8') as log:
        def launch(*command, **options):
            # Only a server started by this disposable probe is traced/cleaned up.
            options.update(stdout=log, stderr=log,
                           env={**options['env'], 'OLLAMA_DEBUG': '1'})
            process = original(*command, **options)
            started.append(process.pid)
            return process
        runtime_module.subprocess.Popen = launch
        try:
            passed = await main(args)
        finally:
            runtime_module.subprocess.Popen = original
    result = json.loads(args.output.read_text(encoding='utf-8'))
    result['diagnostic_server'] = {
        'owned_server_started': bool(started), 'debug_logging': True,
        'runtime_log_sha256': hashlib.sha256(args.runtime_log.read_bytes()).hexdigest(),
        'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'intake_probe_sha256': hashlib.sha256((ROOT / 'tasks/probe_dialogue_followups.py').read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return passed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, default=ROOT / 'tasks/ordinary-followups-live-fixtures.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'tasks/firstcall-startup-trace.json')
    parser.add_argument('--runtime-log', type=Path, default=ROOT / 'tasks/firstcall-ollama-startup.log')
    parser.add_argument('--case', default='robotics_named')
    parser.add_argument('--rounds', type=int, choices=[1, 2], default=2)
    parser.set_defaults(warmup=False)
    sys.exit(0 if asyncio.run(trace(parser.parse_args())) else 1)
