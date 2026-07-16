"""
OPT-IN live validation of the service-backed adapters (S3 Object-Lock + NATS JetStream).

This is deliberately NOT part of `run_all.py` / CI -- those stay offline and dependency-free.
These checks need real services (see ../docker-compose.yml) and are gated on `AATA_LIVE=1`;
without it (or without the services/libs) they SKIP and exit 0, never failing a pipeline.

    docker compose up -d
    # export AWS_* + AATA_WORM=s3 + AATA_WORM_S3_BUCKET + AATA_NATS   (see docs/live-validation.md)
    AATA_LIVE=1 python run_live.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                                   # aata / integrations
sys.path.insert(0, os.path.join(HERE, "tests", "live"))    # flat live modules + _live

from _live import LiveSkip                                 # noqa: E402
import test_nats_jetstream                                 # noqa: E402
import test_s3_objectlock                                  # noqa: E402


def main() -> int:
    if os.getenv("AATA_LIVE") != "1":
        print("AATA_LIVE != 1 -> live validation skipped (offline suite is `python run_all.py`).")
        print("To run it:  docker compose up -d  &&  export env (docs/live-validation.md)  &&")
        print("            AATA_LIVE=1 python run_live.py")
        return 0

    modules = [
        ("S3 OBJECT-LOCK WORM STORE (C9)", test_s3_objectlock),
        ("NATS JETSTREAM STORE-AND-FORWARD (C8/W4)", test_nats_jetstream),
    ]
    skipped, failed = [], []
    for title, mod in modules:
        print("\n" + "=" * 74 + f"\n== {title}\n" + "=" * 74)
        try:
            mod.run()
        except LiveSkip as e:
            print(f"  SKIP: {e}")
            skipped.append(title)
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed.append(title)
        except Exception as e:                             # noqa: BLE001
            print(f"  ERROR: {type(e).__name__}: {e}")
            failed.append(title)

    print("\n" + "=" * 74 + "\n== LIVE RESULT\n" + "=" * 74)
    if failed:
        print(f"  FAILED: {', '.join(failed)}")
        return 1
    if skipped:
        print(f"  SKIPPED (no service/env): {', '.join(skipped)}")
    print("  LIVE OK" if not skipped else "  (nothing failed; some checks skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
