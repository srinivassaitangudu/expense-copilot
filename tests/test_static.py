import csv
import io

from fastapi.testclient import TestClient
from app.main import app
from app.services.imports import parse_csv


def test_review_page_assets_and_sample():
    with TestClient(app) as client:
        page = client.get('/')
        assert page.status_code == 200
        assert 'id="csv-file"' in page.text
        assert 'id="queue"' in page.text
        for asset, content_type in [('/review.js', 'javascript'), ('/styles.css', 'text/css')]:
            response = client.get(asset)
            assert response.status_code == 200
            assert content_type in response.headers['content-type']
        sample = client.get('/sample-transactions.csv')
        assert sample.status_code == 200
        assert 'text/csv' in sample.headers['content-type']
        assert 'attachment' in sample.headers['content-disposition']
        rows = parse_csv(sample.text)
        assert len(rows) == 2
        assert set(csv.DictReader(io.StringIO(sample.text)).fieldnames) == {
            'transaction_id', 'account_id', 'date', 'amount', 'description',
        }
        assert client.get('/healthz').json() == {'ok': True}
