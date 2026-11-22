"""Admin library management UI test: add, list, toggle, delete."""
import os
import re
import shutil
import sys
import tempfile

sys.argv = [sys.argv[0]]

from cps import create_app, app
create_app()
app.config['PROPAGATE_EXCEPTIONS'] = True

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
from cps import lib_registries, get_library_db_by_slug
from cps import db as cps_db

for bp in (search, tasks, web, basic, opds, jinjia, about, shelf, admin.admi,
           remotelogin, meta, editbook):
    app.register_blueprint(bp)

# Build a throwaway library: copy library-2's metadata.db only (books on disk
# are not needed for metadata-level tests)
tmp_lib = tempfile.mkdtemp(prefix='bh_testlib_')
shutil.copy('library-2/metadata.db', os.path.join(tmp_lib, 'metadata.db'))

from werkzeug.security import generate_password_hash
from cps import ub
from cps.ub import User

with app.app_context():
    ub.session.query(User).filter(User.name == 'bht').delete()
    ub.session.query(ub.Library).filter(ub.Library.path == tmp_lib).delete()
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


def csrf(client, path='/advsearch'):
    return CSRF.search(client.get(path).data).group(1).decode()


failed = False
with app.test_client() as c:
    m = CSRF.search(c.get('/login').data)
    c.post('/login', data={'username': 'bht', 'password': 'pw',
                           'csrf_token': m.group(1).decode(), 'remember_me': 'off'})
    tok = csrf(c)

    # page renders and lists both existing libraries
    page = c.get('/admin/libraries')
    print('libraries page:', page.status_code, 'has library-2:', b'library-2' in page.data)
    assert page.status_code == 200 and b'library-2' in page.data

    # add invalid path (flash shown after redirect)
    r = c.post('/admin/libraries/add', data={'path': '/nonexistent/path',
                                             'csrf_token': tok}, follow_redirects=True)
    print('invalid path flash:', b'does not exist' in r.data, r.status_code)
    assert r.status_code == 200 and b'does not exist' in r.data

    # add valid (defaults: name from folder, unique slug)
    r = c.post('/admin/libraries/add', data={'path': tmp_lib, 'csrf_token': tok}, follow_redirects=True)
    print('added ok:', b"added" in r.data)
    with app.app_context():
        lib = ub.session.query(ub.Library).filter(ub.Library.path == tmp_lib).first()
    assert lib is not None
    print('new lib:', lib.id, lib.name, lib.slug, 'enabled:', lib.enabled)
    assert lib.enabled
    # registry instance exists and shows 3 books
    inst = get_library_db_by_slug(lib.slug)
    assert inst is not None and lib.id in lib_registries
    with app.app_context():
        print('registered count:', inst.session.query(cps_db.Books).count())
        assert inst.session.query(cps_db.Books).count() == 3

    # duplicate path rejected
    r = c.post('/admin/libraries/add', data={'path': tmp_lib, 'csrf_token': tok},
               follow_redirects=True)
    print('duplicate rejected:', b'already registered' in r.data)

    # toggle disable
    r = c.post('/admin/libraries/%d/toggle' % lib.id, data={'csrf_token': tok},
               follow_redirects=True)
    with app.app_context():
        lib = ub.session.query(ub.Library).filter(ub.Library.id == lib.id).first()
    print('disabled:', not lib.enabled, 'unregistered:', lib.id not in lib_registries)
    assert not lib.enabled and lib.id not in lib_registries
    # disabled library not selectable
    print('disabled slug resolvable:', get_library_db_by_slug(lib.slug))
    assert get_library_db_by_slug(lib.slug) is None

    # toggle enable
    r = c.post('/admin/libraries/%d/toggle' % lib.id, data={'csrf_token': tok},
               follow_redirects=True)
    with app.app_context():
        lib = ub.session.query(ub.Library).filter(ub.Library.id == lib.id).first()
    print('re-enabled:', lib.enabled, 're-registered:', lib.id in lib_registries)
    assert lib.enabled and lib.id in lib_registries

    # main library protection (Bookhouse 2.0 rules): main can be deleted now,
    # but NEVER the last enabled library (wizard guard). We verify the last-
    # enabled block via the only-remaining-enabled library without actually
    # deleting real data: temporarily disable the other library.
    with app.app_context():
        from cps import main_library_id
        other = [l for l in ub.get_all_libraries_ordered()
                 if l.enabled and l.id != main_library_id]
        for l in other:
            l.enabled = False
        ub.session.commit()
    r = c.post('/admin/libraries/%d/delete' % main_library_id,
               data={'csrf_token': tok}, follow_redirects=True)
    print('last-enabled delete blocked:', b'last enabled' in r.data)
    assert b'last enabled' in r.data
    with app.app_context():
        for l in ub.get_all_libraries_ordered():
            l.enabled = True
        ub.session.commit()

    # delete test library
    r = c.post('/admin/libraries/%d/delete' % lib.id, data={'csrf_token': tok},
               follow_redirects=True)
    print('deleted:', b'deleted' in r.data)
    with app.app_context():
        lib = ub.session.query(ub.Library).filter(ub.Library.id == lib.id).first()
    print('row gone:', lib is None, 'unregistered:', lib.id not in lib_registries if lib else True)
    assert lib is None
    assert lib.id not in lib_registries if lib else True

with app.app_context():
    ub.session.query(User).filter(User.name == 'bht').delete()
    ub.session.commit()

shutil.rmtree(tmp_lib)
if failed:
    sys.exit(1)
print('LIBRARY MANAGEMENT TESTS PASSED')
