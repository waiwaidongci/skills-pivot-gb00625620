import logging
import time
from pathlib import Path
from src.services import quota_execution
from src.services.execution import claim, execute, materialize_due
from src.utils.wakeup import wait

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
heartbeat = Path('/tmp/analysis-heartbeat')


def main():
    while True:
        try:
            materialize_due()
            lease = claim()
            quota_lease = quota_execution.claim()
            heartbeat.touch()
            if lease:
                execute(lease)
                heartbeat.touch()
            if quota_lease:
                quota_execution.execute(quota_lease)
                heartbeat.touch()
            if not lease and not quota_lease:
                wait()
        except Exception:
            log.exception('Worker cycle failed')
            time.sleep(2)


if __name__ == '__main__':
    main()
