"""Real Toad, no input: time the preparation-thread wait the target menu's read sits in."""
import asyncio, faulthandler, json, os, time
from pathlib import Path
from toad.application_lifetime import ApplicationLifetime
from toad.cli import main
OUT = Path('/home/ts/wt/toad-forms-migration/.scratch/p68-live') / os.environ['MENU_RUN']

async def probe(app):
    samples, dumped = [], 0
    for _ in range(75):
        await asyncio.sleep(2)
        start = time.perf_counter()
        task = asyncio.ensure_future(app.preparation.run_thread(lambda: None))
        done, _ = await asyncio.wait({task}, timeout=3)
        if not done and dumped < 3:
            with (OUT / f'stacks-{dumped}.txt').open('w') as f:
                faulthandler.dump_traceback(file=f, all_threads=True)
                f.write('\n--- asyncio tasks ---\n')
                for t in asyncio.all_tasks():
                    f.write(f'{t.get_name()} {t.get_coro()!r}\n')
            dumped += 1
        await task
        samples.append(round(time.perf_counter() - start, 3))
        (OUT / 'waits.json').write_text(json.dumps({'waits': samples, 'running': len(app.preparation._thread_tasks)}))

def started(lifetime):
    app = lifetime.app
    app.call_after_refresh(lambda: asyncio.create_task(probe(app), name='menu-wait-probe'))

if __name__ == '__main__':
    ApplicationLifetime.observe_next_start(started)
    main()
