"""Admin user-edit grant test."""
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
from cps import main_library_id

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
    for n in ('bht_edit_target', 'bht_admin2'):
        u = ub.session.query(User).filter(User.name == n).first()
        if u:
            ub.session.delete(u)
    ub.session.commit()
    a = User()
    a.name = 'bht_admin2'
    a.email = 'a2@x.test'
    a.password = generate_password_hash('pw')
    a.role = 1
    a.sidebar_view = 0x1FF
    ub.session.add(a)
    t = User()
    t.name = 'bht_edit_target'
    t.email = 't@x.test'
    t.password = generate_password_hash('pw')
    t.role = (1 << 1)
    t.sidebar_view = 0x1FF
    ub.session.add(t)
    ub.session.commit()
    lib2 = [l for l in ub.get_all_libraries_ordered() if l.slug == 'library-2'][0]
    tid = t.id

CSRF = re.compile(rb'name="csrf_token"[^>]*value="([^"]+)"')
with app.test_client() as c:
    m = CSRF.search(c.get('/login').data)
    c.post('/login', data={'username': 'bht_admin2', 'password': 'pw',
                           'csrf_token': m.group(1).decode(), 'remember_me': 'off'})
    page = c.get('/admin/user/%d' % tid)
    print('user edit page:', page.status_code,
          'password section ok:', page.status_code == 200,
          'grants section:', b'access_library' in page.data)
    tok = CSRF.search(page.data).group(1).decode()
    r = c.post('/admin/user/%d' % tid,
               data={'csrf_token': tok,
                     'kindle_mail': '',
                     'access_library': [str(main_library_id), str(lib2.id)]},
               follow_redirects=True)
    import re as _re
    m = _re.search(rb'class="alert alert-danger[^"]*">([^<]*)<', r.data) or \
        _re.search(rb'noty[^>]*text[^>]*"([^"]*error[^"]*)"', r.data)
    print('save response has error flash:', bool(m), m.group(1)[:120] if m else '')
    print('save ok:', b'updated' in r.data)
    print('grants:', sorted(ub.get_user_library_ids(tid)))
    assert sorted(ub.get_user_library_ids(tid)) == sorted([main_library_id, lib2.id])
    r = c.post('/admin/user/%d' % tid,
               data={'csrf_token': tok, 'kindle_mail': ''}, follow_redirects=True)
    print('after empty save grants:', ub.get_user_library_ids(tid))
    assert ub.get_user_library_ids(tid) == []

with app.app_context():
    for n in ('bht_edit_target', 'bht_admin2'):
        u = ub.session.query(User).filter(User.name == n).first()
        if u:
            ub.session.delete(u)
    ub.session.commit()
print('USEREDIT GRANT TESTS PASSED')
