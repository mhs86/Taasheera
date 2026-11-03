"""Build one production image at a time without Compose Bake's shared sessions.

The API and migration service share a single backend image. No running service,
private configuration, database or Docker daemon is stopped by this step.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import time


def diagnostics():
    memory = {}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            if key in {'MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'}:
                memory[key] = value.strip()
    except OSError:
        pass
    # Resource counters only, never Docker inspect environment or app.env.
    print('Host memory:', memory, flush=True)
    print('Root disk free MiB:', shutil.disk_usage('/').free // (1024 * 1024), flush=True)


def build_images(log_dir, *, run=subprocess.run, sleep=time.sleep):
    folder = Path(log_dir)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = {**os.environ, 'COMPOSE_BAKE': 'false', 'COMPOSE_PARALLEL_LIMIT': '1'}
    for service in ('api', 'web'):
        for attempt in (1, 2):
            log = folder / f'{service}-{attempt}.log'
            print(f'Building {service} image (attempt {attempt}/2); log: {log}', flush=True)
            with log.open('w') as output:
                log.chmod(0o600)
                result = run(['docker', 'compose', '--parallel', '1', '--progress', 'plain',
                              '-f', 'deploy/aws/compose.yaml', 'build', service],
                             env=env, stdout=output, stderr=subprocess.STDOUT, check=False)
            if result.returncode == 0:
                print(f'Built {service} image.', flush=True)
                break
            text = log.read_text(errors='replace')
            # Retry only a disconnected/expired build session, using cached
            # layers. Package, compile, memory and disk failures fail immediately.
            transient = any(marker in text.lower() for marker in (
                'no active session for', 'failed to get status: rpc error: code = unavailable'))
            if transient and attempt == 1:
                print(f'{service} build session disconnected; retrying this image once.', flush=True)
                sleep(5)
                continue
            diagnostics()
            print(f'{service} image build failed (exit {result.returncode}). Last build output:', flush=True)
            print('\n'.join(text.splitlines()[-40:]), flush=True)
            raise RuntimeError(f'{service} build failed; existing services were not stopped. Full log: {log}')
    print('Both images are ready; migration and API use the same backend image.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log-dir', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        build_images(args.log_dir)
    except RuntimeError as error:
        raise SystemExit(str(error)) from None


if __name__ == '__main__':
    main()
