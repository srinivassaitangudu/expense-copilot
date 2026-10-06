'use strict';

const $ = (id) => document.getElementById(id);
const pageSize = 20;
let rows = [];
let page = 0;
let busy = false;
let queueLoaded = false;
let importedThisSession = false;

function feedback(id, message, error = false) {
  const element = $(id);
  element.textContent = message;
  element.className = `feedback ${error ? 'error' : 'success'}`;
  element.setAttribute('role', error ? 'alert' : 'status');
}

function setBusy(value) {
  busy = value;
  $('csv-file').disabled = value;
  $('import-button').disabled = value || !$('csv-file').files.length;
  $('sample-button').disabled = value;
  $('refresh-button').disabled = value;
  $('previous-button').disabled = value || page === 0;
  $('next-button').disabled = value || (page + 1) * pageSize >= rows.length;
  document.querySelectorAll('.actions button').forEach((button) => { button.disabled = value; });
}

async function request(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { ...options, cache: 'no-store' });
  } catch {
    throw new Error('Could not reach Expense Copilot. Check the server and try again.');
  }
  let data;
  try { data = await response.json(); } catch {
    throw new Error('The server returned an unexpected response. Try again.');
  }
  if (!response.ok) {
    const detail = data.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map((item) => item.msg).join('\n') : 'The request failed. Try again.';
    throw new Error(message);
  }
  return data;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function render() {
  const queue = $('queue');
  queue.replaceChildren();
  $('queue-count').textContent = queueLoaded ? rows.length : '—';
  page = Math.min(page, Math.max(0, Math.ceil(rows.length / pageSize) - 1));
  $('pagination').hidden = rows.length <= pageSize;
  $('page-label').textContent = `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, rows.length)} of ${rows.length}`;
  if (!rows.length) {
    const empty = element('div', 'empty');
    const icon = element('span', 'empty-icon', queueLoaded ? '✓' : '!');
    icon.setAttribute('aria-hidden', 'true');
    empty.append(icon,
      element('h3', '', !queueLoaded ? 'Queue unavailable' : importedThisSession ? 'You’re all caught up' : 'Nothing to review yet'),
      element('p', '', !queueLoaded ? 'Use Refresh to try loading your transactions again.' : importedThisSession ? 'Your decisions are saved. Import another CSV whenever you’re ready.' : 'Import a CSV or try the sample to get started. Previously reviewed transactions stay out of this queue.'));
    queue.append(empty);
  }
  rows.slice(page * pageSize, (page + 1) * pageSize).forEach((row) => {
    const article = element('article', 'transaction');
    const main = element('div', 'transaction-main');
    const info = element('div', 'transaction-info');
    const title = row.merchant || row.description;
    info.append(element('h3', '', title), element('p', 'transaction-meta', `${row.date} · ${row.status}${Number(row.amount) < 0 ? ' · Refund' : ''}`));
    if (row.merchant && row.merchant !== row.description) info.append(element('p', 'transaction-meta', row.description));
    const amount = Number(row.amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    main.append(info, element('span', Number(row.amount) < 0 ? 'amount refund' : 'amount', amount));
    const actions = element('div', 'actions');
    const error = element('p', 'transaction-error');
    error.setAttribute('role', 'alert');
    for (const decision of ['shared', 'personal', 'ignored']) {
      const label = decision === 'ignored' ? 'Ignore' : decision[0].toUpperCase() + decision.slice(1);
      const button = element('button', decision === 'shared' ? 'shared' : 'secondary', label);
      button.type = 'button';
      button.setAttribute('aria-label', `${label}: ${title}`);
      button.addEventListener('click', () => review(row, decision, error));
      actions.append(button);
    }
    article.append(main, actions, error);
    queue.append(article);
  });
  setBusy(busy);
}

async function loadQueue() {
  $('queue').setAttribute('aria-busy', 'true');
  try {
    rows = await request('/api/transactions/unreviewed');
    queueLoaded = true;
    render();
    feedback('review-feedback', '');
  } catch (error) {
    // Retain any previously loaded rows when a refresh fails.
    if (!queueLoaded) render();
    feedback('review-feedback', error.message, true);
  } finally {
    $('queue').setAttribute('aria-busy', 'false');
  }
}

async function importCSV(sample = false) {
  setBusy(true);
  feedback('import-feedback', sample ? 'Loading sample…' : 'Reading CSV…');
  try {
    let csv;
    if (sample) {
      const response = await fetch('/sample-transactions.csv', { cache: 'no-store' });
      if (!response.ok) throw new Error('Could not load the sample. Try downloading the CSV instead.');
      csv = await response.text();
    } else {
      const file = $('csv-file').files[0];
      if (!file) throw new Error('Choose a CSV file first.');
      // A UTF-8 character uses at most four bytes; reject oversized files before reading.
      if (file.size > 4_000_000) throw new Error('CSV is too large. The limit is 1,000,000 characters.');
      csv = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
    }
    if (!csv.trim()) throw new Error('This CSV is empty. Choose a file with transactions.');
    if ([...csv].length > 1_000_000) throw new Error('CSV is too large. The limit is 1,000,000 characters.');
    feedback('import-feedback', 'Importing transactions…');
    const result = await request('/api/transactions/import/csv', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ csv }),
    });
    importedThisSession = true;
    feedback('import-feedback', `Imported ${result.created} transaction${result.created === 1 ? '' : 's'}. Skipped ${result.skipped} already imported. Existing decisions are preserved.`);
    $('csv-file').value = '';
    page = 0;
    await loadQueue();
  } catch (error) {
    const message = error instanceof TypeError ? 'Could not read this file or load the sample. Use a UTF-8 CSV and try again.' : error.message;
    feedback('import-feedback', message, true);
  } finally { setBusy(false); }
}

async function review(row, decision, errorElement) {
  setBusy(true);
  errorElement.textContent = '';
  try {
    await request(`/api/transactions/${encodeURIComponent(row.id)}/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision }),
    });
    rows = rows.filter((item) => item.id !== row.id);
    importedThisSession = true;
    render();
    feedback('review-feedback', `${row.merchant || row.description}: saved as ${decision === 'ignored' ? 'ignored' : decision}.${decision === 'shared' ? ' Nothing was sent to Splitwise.' : ''}`);
    setBusy(false);
    const nextButton = document.querySelector('.actions button') || $('refresh-button');
    nextButton.focus();
  } catch (error) {
    errorElement.textContent = `${error.message} Refresh to check the saved state before retrying if the connection was interrupted.`;
  } finally { setBusy(false); }
}

$('csv-file').addEventListener('change', () => { setBusy(busy); feedback('import-feedback', ''); });
$('import-form').addEventListener('submit', (event) => { event.preventDefault(); if (!busy) importCSV(); });
$('sample-button').addEventListener('click', () => { if (!busy) importCSV(true); });
$('refresh-button').addEventListener('click', async () => { setBusy(true); await loadQueue(); setBusy(false); });
$('previous-button').addEventListener('click', () => { page--; render(); });
$('next-button').addEventListener('click', () => { page++; render(); });
setBusy(true);
loadQueue().finally(() => setBusy(false));
