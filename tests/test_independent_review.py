"""Independent security and privacy regression checks (2026-10-26)."""
import io
import os
import stat
import sqlite3
import json
import copy
import pytest

from openquote_lite.config import load_config, ConfigError
from openquote_lite.http_api import _QuietHandler
from openquote_lite.store import Store
from openquote_lite.profile import Profile
from .conftest import make_request, raw


def test_no_external_plaintext_origin(tmp_path):
    p=tmp_path/'openquote.toml'
    for u in ('http://localhost.evil.test:8787','http://127.0.0.1.evil.test',
              'https://username:password@example.org', 'https://example.org?q=secret', 'https://'):
        p.write_text(f'[instance]\nbase_url = "{u}"\nprofile = "test.json"\n')
        with pytest.raises(ConfigError): load_config(p)


def test_proxy_boolean_cannot_be_string(tmp_path):
    p=tmp_path/'openquote.toml'
    p.write_text('[instance]\nbase_url = "https://example.org"\nprofile = "a.json"\n[http]\ntrust_proxy = "false"\n')
    with pytest.raises(ConfigError, match='TOML boolean'): load_config(p)


def test_server_logs_redact_query_strings_and_unknown_paths(capsys):
    h=object.__new__(_QuietHandler)
    h.requestline='GET /api/v0/profile?email=alice@example.org HTTP/1.1'
    h.log_request(200)
    h.requestline='GET /api/v0/quote-requests/oqr_sensitive-id?name=Alice HTTP/1.1'
    h.log_request(200)
    h.requestline='GET /unknown/pii@example.org HTTP/1.1'
    h.log_request(404)
    logged=capsys.readouterr().err
    assert 'alice@' not in logged and 'Alice' not in logged and 'sensitive' not in logged
    assert '/<id>' in logged and '<unknown-route>' in logged


def test_new_store_is_private_by_default(tmp_path):
    data=tmp_path/'data'
    store=Store(data/'data.sqlite3')
    if os.name=='posix':
        assert stat.S_IMODE(data.stat().st_mode)==0o700
        assert stat.S_IMODE(store.path.stat().st_mode)==0o600


def test_erase_clears_direct_pseudonyms(service):
    result=service.submit(raw(make_request()),client_key='test',channel='http')
    assert result.status==201
    request_id=result.body['request_id']
    assert service.erase(request_id,actor='cli:operator')
    with service.store.transaction(write=False) as con:
        row=con.execute('SELECT payload,postal_code,contact_hash,content_hash,language FROM requests WHERE id=?',(request_id,)).fetchone()
    assert row['payload'] is None
    assert row['postal_code']=='' and row['contact_hash']=='' and row['content_hash']==''
    assert row['language'] is None


def test_jsonld_script_escapes_case_insensitive_closing_tag(service):
    data = copy.deepcopy(service.profile.data)
    data['provider']['name'] = '</SCRIPT><script>alert(1)</script>'
    script = Profile.from_dict(data).jsonld_script('https://example.org')
    assert script.lower().count('</script>') == 1
    assert '\\u003c/SCRIPT>' in script
