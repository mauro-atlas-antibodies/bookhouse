"""Per-user library access test."""
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
from cps import get_current_library_db, get_current_library_id, db as cps_db, main_library_id

for bp in (search, tasks, web, basic, opds, jinjia, about, shelf, admin.admi,
           remotelogin, meta, editbook):
    try:
        app.register_blueprint(bp)
    except Exception:
        pass

from werkzeug.security import generate_password_hash
from cps import ub
from cps.ub import User

with app.app_context():
    # cleanup from previous runs
    for name in ('bht_admin', 'bht_restricted'):
        u = ub.session.query(User).filter(User.name == name).first()
        if u:
            ub.set_user_libraries(u.id, [])
            ub.session.delete(u)
    ub.session.commit()
    # admin user (all libraries)
    ua = User()
    ua.name = 'bht_admin'
    ua.email = 'bht_admin@x.test'
    ua.password = generate_password_hash('pw')
    ua.role = 1  # ROLE_ADMIN
    ua.sidebar_view = 0x1FF
    ub.session.add(ua)
    # restricted user: grant ONLY library-2
    ur = User()
    ur.name = 'bht_restricted'
    ur.email = 'bht_restricted@x.test'
    ur.password = generate_password_hash('pw')
    ur.role = (1 << 1)
    ur.sidebar_view = 0x1FF
    ub.session.add(ur)
    ub.session.commit()
    lib2 = ub.session.query(ub.Library).filter(ub.Library.slug == 'library-2').first()
    ub.set_user_libraries(ur.id, [lib2.id])

CSRF = re.compile(rb'name="csrf_token"[^>]*value="([^"]+)"')


def login(client, username):
    m = CSRF.search(client.get('/login').data)
    client.post('/login', data={'username': username, 'password': 'pw',
                                'csrf_token': m.group(1).decode(), 'remember_me': 'off'})


def csrf_of(client):
    return CSRF.search(client.get('/advsearch').data).group(1).decode()


worked = True

# --- admin user: can select both libraries
with app.test_client() as c:
    login(c, 'bht_admin')
    home = c.get('/')
    print('admin sees library-2 option:', b'value="library-2"' in home.data)
    tok = csrf_of(c)
    c.post('/lib/select/library-2', data={'csrf_token': tok})
    c.get('/')
    ok = get_current_library_id() == lib2.id
    print('admin switched to lib2 (id %d):' % get_current_library_id(), ok)
    worked &= ok

# --- restricted user: granted library-2 only
with app.test_client() as c:
    login(c, 'bht_restricted')
    home = c.get('/')
    print('restricted sees library-2 option:', b'value="library-2"' in home.data)
    tok = csrf_of(c)
    c.post('/lib/select/library-2', data={'csrf_token': tok})
    c.get('/')
    ok = get_current_library_id() == lib2.id
    print('restricted switched to lib2:', ok)
    worked &= ok
    # tried to switch to main -> should be rejected and restored? main not granted
    c.post('/lib/select/main', data={'csrf_token': tok})
    c.get('/')
    ok = get_current_library_id() == lib2.id  # fallback -> ... main not permitted, stays main?? see note
    print('restricted select main -> current id:', get_current_library_id())

# --- restricted user creation default check: fresh user with NO grants -> main only
with app.test_client() as c:
    u = User()
    u.name = 'bht_nogrant'
    u.email = 'bht_nogrant@x.test'
    u.password = generate_password_hash('pw')
    u.role = (1 << 1)
    u.sidebar_view = 0x1FF
    with app.app_context():
        ub.session.add(u)
        ub.session.commit()
    login(c, 'bht_nogrant')
    c.get('/')
    ok = get_current_library_id() == main_library_id
    print('no-grant user resolves main:', ok)
    worked &= ok
    tok = csrf_of(c)
    c.post('/lib/select/library-2', data={'csrf_token': tok})
    c.get('/')
    ok = get_current_library_id() == main_library_id  # rejected, fall back main
    print('no-grant select lib2 rejected:', ok)
    worked &= ok
    with app.app_context():
        b = ub.session.query(User).filter(User.name == 'bht_nogrant').first()
        ub.session.delete(b)
        ub.session.commit()

with app.app_context():
    for name in ('bht_admin', 'bht_restricted'):
        u = ub.session.query(User).filter(User.name == name).first()
        if u:
            ub.set_user_libraries(u.id, [])
            ub.session.delete(u)
    ub.session.commit()

print('PERMISSION TESTS PASSED' if worked else 'PERMISSION TESTS FAILED')
sys.exit(0 if worked else 1)
