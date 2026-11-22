"""Bookhouse smoke test: exercised migrated modules via Flask test client."""
import os
import re
import sys

sys.argv = [sys.argv[0]]  # prevent cps.cli from parsing args

from cps import create_app, app

create_app()

from cps.web import web
from cps.search import search
from cps.basic import basic
from cps.jinjia import jinjia
from cps.about import about
from cps.shelf import shelf
from cps import admin
from cps.remotelogin import remotelogin
from cps.search_metadata import meta
from cps.editbooks import editbook
from cps.opds import opds
from cps.tasks_status import tasks
from cps.kobo_auth import kobo_auth
from cps.gdrive import gdrive

BPS = [search, tasks, web, basic, opds, jinjia, about, shelf, admin.admi,
       remotelogin, meta, editbook, kobo_auth, gdrive]
for bp in BPS:
    try:
        app.register_blueprint(bp)
    except Exception as e:
        print('skip blueprint:', e)

from werkzeug.security import generate_password_hash
from cps import ub
from cps.ub import User

USERNAME = 'bht_smoke'
PASSWORD = 'smokepass'

with app.app_context():
    # idempotent: remove leftovers from aborted runs, then create fresh user
    ub.session.query(User).filter(User.name == USERNAME).delete()
    ub.session.commit()
    u = User()
    u.name = USERNAME
    u.email = USERNAME + '@bookhouse.test'
    u.password = generate_password_hash(PASSWORD)
    u.role = (1 << 0) | (1 << 1)  # ROLE_ADMIN | ROLE_DOWNLOAD
    u.sidebar_view = 0x1FF  # all sidebar visibility bits
    ub.session.add(u)
    ub.session.commit()

FAILURES = []


def check(name, resp, expect=200):
    ok = resp.status_code == expect
    print(('PASS' if ok else 'FAIL'), name, resp.status_code, len(resp.data))
    if not ok:
        FAILURES.append(name)


with app.test_client() as c:
    page = c.get('/login')
    m = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', page.data)
    r = c.post('/login', data={'username': USERNAME, 'password': PASSWORD,
                               'csrf_token': m.group(1).decode(), 'remember_me': 'off'})
    print('login:', r.status_code, r.headers.get('Location'))

    # search.py
    r = c.get('/search?query=book')
    check('search redirect', r, 302)
    loc = r.headers.get('Location') or '/search/stored?query=book'
    r = c.get(loc)
    check('search results page', r, 200)
    check('advsearch form', c.get('/advsearch'))
    m2 = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', c.get('/advsearch').data)
    check('advsearch POST', c.post('/advsearch', data={'submit': 'Submit',
                                                       'csrf_token': m2.group(1).decode()}), 302)

    # resolve a real book id for detail views
    with app.app_context():
        from cps import get_current_library_db, db as cps_db
        calibre_db = get_current_library_db()
        book_id = calibre_db.session.query(cps_db.Books).first().id
        print('using book_id:', book_id)

    # basic.py
    check('basic index', c.get('/basic?query='))
    check('basic search', c.get('/basic?query=book'))
    check('basic book', c.get('/basic_book/%d' % book_id))

    # about.py
    check('stats', c.get('/stats'))

    # shelf.py (read endpoint needs a shelf id; 404-vs-render distinguished elsewhere)
    check('shelf create form', c.get('/shelf/create'))

    # opds.py (basic auth)
    check('opds index', c.get('/opds/', auth=(USERNAME, PASSWORD)))
    check('opds new', c.get('/opds/new', auth=(USERNAME, PASSWORD)))
    check('opds discover', c.get('/opds/discover', auth=(USERNAME, PASSWORD)))
    check('opds authors', c.get('/opds/author', auth=(USERNAME, PASSWORD)))
    check('opds series', c.get('/opds/series', auth=(USERNAME, PASSWORD)))
    check('opds search', c.get('/opds/search/book', auth=(USERNAME, PASSWORD)))

    # admin.py (read-only pages)
    check('admin view', c.get('/admin/view'))
    check('admin viewconfig', c.get('/admin/viewconfig'))
    check('admin config', c.get('/admin/config'))
    check('admin usertable', c.get('/admin/usertable'))
    check('admin dbconfig form', c.get('/admin/dbconfig'))

    # editbooks.py read path
    check('edit book form', c.get('/admin/book/%d' % book_id))

    # editbooks.py: calibre mutations must be hard-blocked
    token = m2.group(1).decode()
    r = c.post('/delete/%d' % book_id, data={'csrf_token': token})
    print('delete blocked:', r.status_code)
    assert r.status_code == 403
    r = c.post('/upload', data={'csrf_token': token})
    print('upload blocked:', r.status_code)
    assert r.status_code == 403

    # web.py read paths
    check('index newest', c.get('/'))
    check('index page 2', c.get('/page/2'))
    check('author typeahead', c.get('/get_authors_json?q='))

    # helper.py via cover + download endpoints
    with app.app_context():
        from cps import get_current_library_db, db as cps_db
        calibre_db = get_current_library_db()
        fmt = calibre_db.session.query(cps_db.Data.format).filter(cps_db.Data.book == book_id).first()
        book_format = fmt[0] if fmt else None
        print('book format:', book_format)
    if book_format:
        r = c.get('/download/%d/%s' % (book_id, book_format))
        print('download:', r.status_code, len(r.data))
        assert r.status_code in (200, 302)
    r = c.get('/cover/%d' % book_id)
    print('cover:', r.status_code, len(r.data))
    assert r.status_code in (200, 302)

    # shelf.py roundtrip: create shelf -> show shelf -> add book -> show again
    r = c.get('/shelf/create')
    m3 = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', r.data)
    r = c.post('/shelf/create', data={'title': 'smokeshelf', 'csrf_token': m3.group(1).decode()},
               follow_redirects=True)
    print('shelf create:', r.status_code)
    shelf_id = None
    with app.app_context():
        from cps import ub as ub_mod
        row = ub_mod.session.query(ub_mod.Shelf).filter(ub_mod.Shelf.name == 'smokeshelf').first()
        if row:
            shelf_id = row.id
    print('shelf id:', shelf_id)
    assert shelf_id
    page = c.get('/shelf/%d' % shelf_id)
    check('show shelf empty', page, 200)
    r = c.post('/shelf/add/%d/%d' % (shelf_id, book_id), data={'csrf_token': m3.group(1).decode()},
               follow_redirects=True)
    print('shelf add:', r.status_code)
    page = c.get('/shelf/%d' % shelf_id)
    check('show shelf with book', page, 200)
    # cleanup shelf
    r = c.post('/shelf/delete/%d' % shelf_id, data={'csrf_token': m3.group(1).decode()},
               follow_redirects=True)
    print('shelf delete:', r.status_code)

with app.app_context():
    ub.session.query(User).filter(User.name == USERNAME).delete()
    ub.session.commit()

print('TEST USERS CLEANED')
if FAILURES:
    print('FAILURES:', FAILURES)
    sys.exit(1)
print('ALL SMOKE TESTS PASSED')
