"""Optional browser regression check using synthetic data and a temporary database.

Install Playwright separately; use --browser for an existing Chromium executable.
No application server, credentials, or financial exports are needed.
"""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
HEADER = 'transaction_id,account_id,date,amount,description\n'


def run(page, base, screenshots):
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base)
    expect(page.get_by_role('heading', name='Nothing to review yet')).to_be_visible()
    expect(page.locator('#import-button')).to_be_disabled()
    page.get_by_role('button', name='Try sample transactions').click()
    expect(page.locator('#import-feedback')).to_contain_text('Imported 2 transactions. Skipped 0')
    expect(page.locator('.transaction')).to_have_count(2)
    if screenshots:
        page.screenshot(path=str(screenshots / 'desktop-review.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(screenshots / 'mobile-review.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})
    page.get_by_role('button', name='Personal: Sample lunch', exact=True).click()
    expect(page.locator('.transaction')).to_have_count(1)
    page.get_by_role('button', name='Shared: Sample groceries', exact=True).click()
    expect(page.get_by_role('heading', name='You’re all caught up')).to_be_visible()
    expect(page.locator('#review-feedback')).to_contain_text('Nothing was sent to Splitwise')
    page.reload()
    expect(page.locator('.transaction')).to_have_count(0)
    page.get_by_role('button', name='Try sample transactions').click()
    expect(page.locator('#import-feedback')).to_contain_text('Imported 0 transactions. Skipped 2')
    expect(page.locator('.transaction')).to_have_count(0)

    def upload(content):
        page.locator('#csv-file').set_input_files({
            'name': 'synthetic.csv', 'mimeType': 'text/csv', 'buffer': content.encode(),
        })
        page.get_by_role('button', name='Import transactions').click()

    upload(HEADER + 'bad,checking,not-a-date,1,Invalid\n')
    expect(page.locator('#import-feedback')).to_contain_text('Row 2: use an ISO date')
    expect(page.locator('.transaction')).to_have_count(0)
    upload('')
    expect(page.locator('#import-feedback')).to_contain_text('This CSV is empty')
    # Descriptions must render as text, including hostile HTML.
    hostile = '<img src=x onerror=window.uiInjected=true>'
    upload(HEADER + f'html,checking,2026-10-03,-9.25,{hostile}\n')
    expect(page.locator('.transaction h3')).to_have_text(hostile)
    assert page.locator('.transaction img').count() == 0
    assert page.evaluate('window.uiInjected') is None
    expect(page.locator('.transaction-meta')).to_contain_text('Refund')
    expect(page.locator('.amount')).to_have_text('-9.25')

    # A failed save keeps the row and offers a retry; no success is fabricated.
    review_url = '**/api/transactions/*/review'
    page.route(review_url, lambda route: route.fulfill(status=500, json={'detail': 'Synthetic save failure'}))
    page.get_by_role('button', name=f'Ignore: {hostile}', exact=True).click()
    expect(page.locator('.transaction-error')).to_contain_text('Synthetic save failure')
    expect(page.locator('.transaction')).to_have_count(1)
    page.unroute(review_url)
    page.get_by_role('button', name=f'Ignore: {hostile}', exact=True).click()
    expect(page.locator('.transaction')).to_have_count(0)

    # Pagination, duplicate IDs and mobile layout with a real upload.
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['transaction_id', 'account_id', 'date', 'amount', 'description'])
    for i in range(21):
        writer.writerow([f'page-{i}', 'demo', '2026-10-01', '2.50', f'Synthetic purchase {i}'])
    upload(buffer.getvalue())
    expect(page.locator('#import-feedback')).to_contain_text('Imported 21 transactions')
    expect(page.locator('.transaction')).to_have_count(20)
    page.get_by_role('button', name='Next', exact=True).click()
    expect(page.locator('.transaction')).to_have_count(1)
    expect(page.locator('#page-label')).to_have_text('21–21 of 21')
    page.get_by_role('button', name='Previous', exact=True).click()
    expect(page.locator('.transaction')).to_have_count(20)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')

    # Refresh failures retain loaded rows; an initial load failure is not an empty queue.
    queue_url = '**/api/transactions/unreviewed'
    page.route(queue_url, lambda route: route.abort())
    page.get_by_role('button', name='Refresh', exact=True).click()
    expect(page.locator('#review-feedback')).to_contain_text('Could not reach Expense Copilot')
    expect(page.locator('.transaction')).to_have_count(20)
    page.reload()
    expect(page.get_by_role('heading', name='Queue unavailable')).to_be_visible()
    page.unroute(queue_url)
    page.get_by_role('button', name='Refresh', exact=True).click()
    expect(page.locator('.transaction')).to_have_count(20)
    assert not errors, errors
    print('Browser checks passed: import, all review decisions, persistence, duplicates, validation, safe text rendering, pagination, failures, mobile layout.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', default=sys.executable, help='Python with application requirements installed')
    parser.add_argument('--browser', help='Existing Chromium executable; otherwise use Playwright Chromium')
    parser.add_argument('--screenshots', type=Path, help='Optional output directory; keep outside the repository')
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='expense-copilot-ui-') as directory:
        env = {**os.environ, 'DATABASE_URL': f'sqlite:///{directory}/test.db'}
        subprocess.run([args.python, '-m', 'scripts.init_db'], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        with open(Path(directory) / 'server.log', 'w+') as log:
            server = subprocess.Popen([args.python, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port), '--no-access-log'], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError('Test server exited before startup')
                    try:
                        with urlopen(base + '/healthz', timeout=1) as response:
                            assert json.load(response) == {'ok': True}
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError('Test server did not start')
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
                    try:
                        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                        run(page, base, args.screenshots)
                    finally:
                        browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == '__main__':
    main()
