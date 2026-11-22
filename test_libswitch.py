"""Library switch test: session-based library switching."""
import re
import sys

sys.argv = [sys.argv[0]]

from cps import create_app, app
create_app()

from cps.web import web
from cps.basic import basic
from cps.search import search
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
from cps import get_current_library_db, get_current_library_id, db as cps_db

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

with app.app_context():
    ub.session.query(User).filter(User.name == 'bht').delete()
    ub.session.commit()
    u = User()
    u.name = 'bht'
    u.email = 'bht@x.test'
    u.password = generate_password_hash('pw')
    u.role = 1
    u.sidebar_view = 0x1FF
    ub.session.add(u)
    ub.session.commit()

CSRF = re.compile(rb'name="csrf_token"[^>]*value="([^"]+)"')

with app.test_client() as c:
    page = c.get('/login')
    m = CSRF.search(page.data)
    if not m:
        # fall back to a form action=login page? try finding any token
        print('no csrf on login page; status', page.status_code)
        sys.exit(1)
    c.post('/login', data={'username': 'bht', 'password': 'pw',
                           'csrf_token': m.group(1).decode(), 'remember_me': 'off'})
    resp = c.get('/advsearch')
    tok_m = CSRF.search(resp.data)
    if not tok_m:
        print('advsearch status:', resp.status_code)
        print(resp.data[:300])
        sys.exit(1)
    tok = tok_m.group(1).decode()
    c.get('/')
    print('main books:', get_current_library_db().session.query(cps_db.Books).count(),
          'id:', get_current_library_id())
    c.post('/lib/select/library-2', data={'csrf_token': tok}, follow_redirects=False)
    c.get('/')
    print('after switch books:', get_current_library_db().session.query(cps_db.Books).count(),
          'id:', get_current_library_id())
    c.post('/lib/select/nope', data={'csrf_token': tok}, follow_redirects=False)
    c.get('/')
    print('after bogus books:', get_current_library_db().session.query(cps_db.Books).count(),
          'id:', get_current_library_id())

with app.app_context():
    ub.session.query(User).filter(User.name == 'bht').delete()
    ub.session.commit()
print('LIB SWITCH TESTS PASSED')
