"""Fresh-deployment wizard + default-library refactor test."""
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
from cps import main_library_id, get_current_library_id

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
    for n in ('bht_admin3',):
        u = ub.session.query(User).filter(User.name == n).first()
        if u:
            ub.session.delete(u)
    ub.session.commit()
    a = User()
    a.name = 'bht_admin3'
    a.email = 'a3@x.test'
    a.password = generate_password_hash('pw')
    a.role = 1
    a.sidebar_view = 0x1FF
    ub.session.add(a)
    ub.session.commit()
    libs = ub.get_all_libraries_ordered()
    main = [l for l in libs if l.slug == 'main'][0]
    lib2 = [l for l in libs if l.slug == 'library-2'][0]

CSRF = re.compile(rb'name="csrf_token"[^>]*value="([^"]+)"')

# --- normal state: is_default migrated correctly
with app.app_context():
    d = ub.get_default_library()
    print('migrated default:', d.name if d else None, d.is_default if d else None)
    assert d is not None and d.is_default

try:
    # simulate fresh deployment: no default, no enabled libraries
    with app.app_context():
        ub.session.query(ub.Library).update({ub.Library.is_default: False,
                                             ub.Library.enabled: False})
        ub.session.commit()
        import cps
        cps.main_library_id = None

    # admin: login page passes guard, index redirects to library management
    with app.test_client() as c:
        m = CSRF.search(c.get('/login').data)
        c.post('/login', data={'username': 'bht_admin3', 'password': 'pw',
                               'csrf_token': m.group(1).decode(), 'remember_me': 'off'})
        r = c.get('/')
        print('admin index redirect:', r.status_code, r.headers.get('Location'))
        assert r.status_code == 302 and 'admin/libraries' in (r.headers.get('Location') or '')
        page = c.get('/admin/libraries')
        print('library mgmt reachable:', page.status_code, b'Add Library' in page.data)
        assert page.status_code == 200
        book_page = c.get('/book/2')
        print('books blocked while no default:', book_page.status_code)
        assert book_page.status_code == 302

    # anonymous: setup wizard
    with app.test_client() as c:
        r = c.get('/', follow_redirects=False)
        print('anon index:', r.status_code, b'Welcome to Bookhouse' in r.data)
        assert r.status_code == 200 and b'Welcome to Bookhouse' in r.data

    # re-enable main via toggle (simulates clicking Enable in UI)
    with app.test_client() as c:
        m = CSRF.search(c.get('/login').data)
        c.post('/login', data={'username': 'bht_admin3', 'password': 'pw',
                               'csrf_token': m.group(1).decode(), 'remember_me': 'off'})
        tok = CSRF.search(c.get('/admin/libraries').data).group(1).decode()
        with app.app_context():
            main_row = ub.get_library(main.id)
            main_row.enabled = True
            ub.update_library(main_row)
        # zero default: first enabled library added via UI path becomes default;
        # here use the set-default endpoint on main
        admin_id_row = ub.session.query(User).filter(User.name == 'bht_admin3').first()
        r = c.post('/admin/libraries/%d/default' % main.id, data={'csrf_token': tok},
                   follow_redirects=True)
        print('set default ok:', b'default library' in r.data)
        with app.app_context():
            d = ub.get_default_library()
            print('default after promotion:', d.slug if d else None)
        assert d is not None and d.slug == 'main'
        # index now works again
        r = c.get('/')
        print('index restored:', r.status_code)
        assert r.status_code == 200
finally:
    # restore exact original state
    with app.app_context():
        ub.set_default_library(main.id)
        import cps
        cps.main_library_id = main.id
        for lib in ub.get_all_libraries_ordered():
            lib.enabled = True
        ub.session.commit()

with app.app_context():
    ub.session.query(User).filter(User.name == 'bht_admin3').delete()
    ub.session.commit()
print('WIZARD + DEFAULT TESTS PASSED')
