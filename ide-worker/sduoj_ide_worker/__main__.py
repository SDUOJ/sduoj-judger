import argparse
import asyncio
import logging
import os


def main(*, prepare=None):
    parser = argparse.ArgumentParser(description='SDUOJ Redis-only IDE worker')
    parser.add_argument('--role', choices=('all', 'lsp', 'debug'), default='all')
    parser.add_argument('--language', choices=('c', 'cpp', 'java', 'python'))
    args = parser.parse_args()
    if args.role == 'lsp' and not args.language:
        parser.error('--language is required for an LSP worker')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    if args.role == 'all' or os.getenv('SDUOJ_IDE_NACOS_ENABLED') == '1':
        # The hash is a change detector, never proof that this process fetched
        # configuration. Inherited environment must not bypass a fresh fetch.
        from .nacos import bootstrap
        asyncio.run(bootstrap())
    if prepare is not None:
        prepare()
    if args.role == 'all':
        from .service import Service
        asyncio.run(Service().run())
    else:
        from .worker import Worker
        asyncio.run(Worker(args.role, args.language).run())


if __name__ == '__main__':
    main()
