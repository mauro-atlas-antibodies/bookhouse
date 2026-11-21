# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#    Copyright (C) 2018-2019 OzzieIsaacs, cervinko, jkrehm, bodybybuddha, ok11,
#                            andy29485, idalin, Kyosfonica, wuqi, Kennyl, lemmsh,
#                            falgh1, grunjol, csitko, ytils, xybydy, trasba, vrabe,
#                            ruben-herold, marblepebble, JackED42, SiphonSquirrel,
#                            apetresc, nanu-c, mutschler
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.
__package__ = "cps"

import sys
import os
import mimetypes

from flask import Flask
from flask.sessions import SecureCookieSessionInterface
from flask_themes2 import Themes
from .MyLoginManager import MyLoginManager
from flask_principal import Principal

from . import logger
from .cli import CliParameter
from .reverseproxy import ReverseProxied
from .server import WebServer
from .dep_check import dependency_check
from .updater import Updater
from . import config_sql
from . import cache_buster
from . import ub, db

try:
    from flask_limiter import Limiter
    limiter_present = True
except ImportError:
    limiter_present = False
try:
    from flask_wtf.csrf import CSRFProtect
    wtf_present = True
except ImportError:
    wtf_present = False


mimetypes.init()
mimetypes.add_type('application/xhtml+xml', '.xhtml')
mimetypes.add_type('application/epub+zip', '.epub')
mimetypes.add_type('application/epub+zip', '.kepub')
mimetypes.add_type('application/fb2+zip', '.fb2')
mimetypes.add_type('application/x-mobipocket-ebook', '.mobi')
mimetypes.add_type('application/octet-stream', '.prc')
mimetypes.add_type('application/x-mobipocket-ebook', '.azw')
mimetypes.add_type('application/x-mobipocket-ebook', '.azw3')
mimetypes.add_type('application/x-cbr', '.cbr')
mimetypes.add_type('application/x-cbz', '.cbz')
mimetypes.add_type('application/x-tar', '.cbt')
mimetypes.add_type('application/x-7z-compressed', '.cb7')
mimetypes.add_type('image/vnd.djvu', '.djv')
mimetypes.add_type('image/vnd.djvu', '.djvu')
mimetypes.add_type('application/mpeg', '.mpeg')
mimetypes.add_type('audio/mpeg', '.mp3')
mimetypes.add_type('audio/x-m4a', '.m4a')
mimetypes.add_type('audio/x-m4a', '.m4b')
mimetypes.add_type('audio/x-hx-aac-adts', '.aac')
mimetypes.add_type('audio/vnd.dolby.dd-raw', '.ac3')
mimetypes.add_type('video/x-ms-asf', '.asf')
mimetypes.add_type('audio/ogg', '.ogg')
mimetypes.add_type('application/ogg', '.oga')
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/x-ms-reader', '.lit')
mimetypes.add_type('text/javascript', '.js')
mimetypes.add_type('text/rtf', '.rtf')

log = logger.create()

app = Flask(__name__)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    REMEMBER_COOKIE_SAMESITE='Strict',
    WTF_CSRF_SSL_STRICT=False,
    SESSION_COOKIE_NAME=os.environ.get('COOKIE_PREFIX', "") + "session",
    REMEMBER_COOKIE_NAME=os.environ.get('COOKIE_PREFIX', "") + "remember_token"
)

lm = MyLoginManager()

cli_param = CliParameter()

config = config_sql.ConfigSQL()

if wtf_present:
    csrf = CSRFProtect()
else:
    csrf = None

calibre_db = db.CalibreDB(app)

# Library registry: one CalibreDB instance per enabled library.
# The main library reuses the legacy global calibre_db instance.
lib_registries = {}
main_library_id = None
# Bookhouse: app.db path used when registering CalibreDB instances at runtime
_registry_settings_path = None


def get_library_db(lib_id):
    """Return the CalibreDB instance registered for a library id."""
    return lib_registries.get(lib_id)


def get_library_db_by_slug(slug):
    """Return the CalibreDB instance registered for a library slug."""
    lib = ub.get_library_by_slug(slug)
    if lib is None:
        return None
    return lib_registries.get(lib.id)


def get_current_library_db():
    """Resolve the CalibreDB instance for the current request.

    Resolution order: explicit ?lib=<slug> URL parameter, then the library
    slug stored in the Flask session (library switcher), then the default
    library. Per-user access is enforced everywhere: users without
    permission fall back to their default library (main for users without
    grants, first granted otherwise).
    """
    current_db = None
    try:
        from flask import session as flask_session, request as flask_request
        from .cw_login import current_user
        # 1. explicit URL parameter (shareable links, OPDS basic auth)
        slug = flask_request.args.get('lib') or flask_session.get('current_library_slug')
        if (slug and flask_request.args.get('lib')
                and not getattr(flask_request, '_bh_lib_persisted', False)):
            # persist explicit switch for browser navigation (OPDS agents
            # typically have no session; persist is harmless there)
            flask_session['current_library_slug'] = slug
            flask_request._bh_lib_persisted = True
        if slug:
            lib = ub.get_library_by_slug(slug)
            if lib is not None and user_permitted_for_library(current_user, lib):
                current_db = lib_registries.get(lib.id)
    except RuntimeError:
        # outside request context (background tasks): default library
        pass
    if current_db is None:
        # per-user fallback: main unless the user has explicit grants
        try:
            from .cw_login import current_user
            from .constants import ROLE_ADMIN
            is_admin = bool(current_user is not None and current_user.role is not None
                            and (current_user.role & ROLE_ADMIN))
            grants = ub.get_user_library_ids(current_user.id)
        except Exception:
            is_admin, grants = True, []
        if (not is_admin) and grants:
            fallback = next((get_library_db(gid) for gid in grants
                             if get_library_db(gid) is not None), None)
            if fallback is not None:
                return fallback
        if lib_registries and main_library_id is not None:
            return get_library_db(main_library_id) or calibre_db
        return calibre_db
    return current_db


def user_permitted_for_library(user, lib):
    """Per-user access check (see ub.user_can_access_library)."""
    from .constants import ROLE_ADMIN
    try:
        if user is None or user.id is None:
            return False
        is_admin = bool(user.role is not None and (user.role & ROLE_ADMIN))
        return ub.user_can_access_library(user.id, lib.id, main_library_id, is_admin)
    except Exception:
        return False


def get_permitted_libraries():
    """Enabled libraries the current user may access (list of Library rows)."""
    try:
        from .cw_login import current_user
    except Exception:
        current_user = None
    try:
        libs = ub.get_enabled_libraries()
    except Exception:
        return []
    return [lib for lib in libs if user_permitted_for_library(current_user, lib)]


def get_current_library_id():
    """Id of the library returned by get_current_library_db()."""
    cdb = get_current_library_db()
    for lib_id, db_inst in lib_registries.items():
        if db_inst is cdb:
            return lib_id
    return main_library_id


def get_current_library_slug():
    """Slug of the library currently selected in the session (or None)."""
    from flask import session as flask_session
    return flask_session.get('current_library_slug')


def get_current_main_library_id():
    """Id of the main (default) library."""
    return main_library_id


def set_default_library_id(lib_id):
    """Rebind the module-level default library id + persist the flag."""
    global main_library_id
    main_library_id = lib_id
    ub.set_default_library(lib_id)


def initialize_first_library_guard(app):
    """Fresh deployments have zero libraries: send users to the setup wizard.

    Only authenticated admins may pass through to the library management
    pages; everyone else is shown the setup page (admins get the add form,
    others are told to wait for the admin).
    """
    from flask import request, redirect, url_for
    from .render_template import render_title_template
    from flask_babel import gettext as _

    @app.before_request
    def _bookhouse_setup_guard():  # noqa
        # once a default exists, everything proceeds normally
        if ub.get_default_library() is not None:
            return None
        endpoint = request.endpoint or ''
        allowed_prefixes = ('web.login', 'web.logout', 'static', 'remotelogin.')
        allowed_exact = ('admin.list_libraries', 'admin.add_library_ui',
                         'admin.toggle_library', 'admin.delete_library_ui',
                         'admin.set_default_library_ui', 'basic.select_library')
        if any(endpoint.startswith(p) for p in allowed_prefixes):
            return None
        if endpoint in allowed_exact or request.path.split('?')[0].startswith('/admin/libraries'):
            return None
        from .cw_login import current_user
        if current_user is not None and getattr(current_user, 'is_authenticated', False):
            return redirect(url_for('admin.list_libraries'))
        return render_title_template('setup.html',
                                     title=_('Welcome to Bookhouse'),
                                     page='setup')


def register_library_in_registry(lib_id):
    """Build and register a CalibreDB instance for a library at runtime."""
    global _registry_settings_path
    if lib_id in lib_registries:
        return None
    lib = ub.get_library(lib_id)
    if lib is None:
        return None
    if config.config_calibre_dir and lib.path == config.config_calibre_dir:
        # main library: already served by the global calibre_db instance
        lib_registries[lib.id] = calibre_db
        return calibre_db
    lib_db = db.CalibreDB(app)
    lib_db.update_config(config, lib.path, _registry_settings_path)
    lib_registries[lib.id] = lib_db
    return lib_db


def unregister_library_in_registry(lib_id):
    """Drop a library's CalibreDB instance from the registry."""
    return lib_registries.pop(lib_id, None)

# Bookhouse: app.db models whose rows are scoped by library_id
LIBRARY_ID_TABLES_MODELS = None  # populated after ub is imported (module bottom)


updater_thread = Updater()
web_server = WebServer()
themes_extension = Themes()

if limiter_present:
    limiter = Limiter(key_func=True, headers_enabled=True, in_memory_fallback_enabled=True, default_limits=[],
                      swallow_errors=True)
else:
    limiter = None

class ScriptNameSessionInterface(SecureCookieSessionInterface):
    def get_cookie_path(self, app):
        # Called once per response, after request context exists
        return app.wsgi_app.script_name.rstrip("/") or "/"


def create_app():
    app.session_interface = ScriptNameSessionInterface()
    if csrf:
        csrf.init_app(app)

    cli_param.init()

    ub.init_db(cli_param.settings_path)
    # pylint: disable=no-member
    encrypt_key, error = config_sql.get_encryption_key(os.path.dirname(cli_param.settings_path))

    config_sql.load_configuration(ub.session, encrypt_key)
    config.init_config(ub.session, encrypt_key, cli_param)

    if error:
        log.error(error)

    ub.password_change(cli_param.user_credentials)

    if sys.version_info < (3, 0):
        log.info(
            '*** Python2 is EOL since end of 2019, this version of Bookhouse is no longer supporting Python2, '
            'please update your installation to Python3 ***')
        print(
            '*** Python2 is EOL since end of 2019, this version of Bookhouse is no longer supporting Python2, '
            'please update your installation to Python3 ***')
        web_server.stop(True)
        sys.exit(5)

    lm.login_view = 'web.login'
    lm.anonymous_user = ub.Anonymous
    lm.session_protection = 'strong' if config.config_session == 1 else "basic"

    ub.bootstrap_library(config.config_calibre_dir)
    if config.config_calibre_dir:
        calibre_db.update_config(config, config.config_calibre_dir, cli_param.settings_path)

    # Load the library registry from the app DB registry table.
    global main_library_id
    global _registry_settings_path
    _registry_settings_path = cli_param.settings_path
    lib_registries.clear()
    # Bookhouse: default library (replaces the legacy 'main' concept).
    # The row matching config_calibre_dir (if any) bootstraps as default;
    # a fresh deployment may have no default at all.
    default_lib = ub.get_default_library()
    for lib in ub.get_enabled_libraries():
        if lib.path == config.config_calibre_dir:
            lib_db = calibre_db  # legacy global instance serves the legacy dir
        else:
            lib_db = db.CalibreDB(app)
            lib_db.update_config(config, lib.path, cli_param.settings_path)
        lib_registries[lib.id] = lib_db
        if default_lib is not None and lib.id == default_lib.id:
            main_library_id = lib.id
    if main_library_id is None and default_lib is None:
        # no explicit default: fall back to the legacy config path's library,
        # else the first enabled library, else None (fresh deployment)
        legacy = next((lib for lib in ub.get_enabled_libraries()
                       if lib.path == config.config_calibre_dir), None)
        chosen = legacy or (ub.get_enabled_libraries()[0]
                            if ub.get_enabled_libraries() else None)
        if chosen is not None:
            ub.set_default_library(chosen.id)
            main_library_id = chosen.id

    # One teardown for all library instances: Flask 3 no longer allows
    # registering teardown_appcontext after the first request, and library
    # instances can be created at runtime (admin library management).
    def _teardown_libraries(exception):
        for inst in list(lib_registries.values()):
            try:
                inst.teardown(exception)
            except Exception:
                pass
    app.teardown_appcontext(_teardown_libraries)

    updater_thread.init_updater(config, web_server)
    # Perform dry run of updater and exit afterward
    if cli_param.dry_run:
        updater_thread.dry_run()
        sys.exit(0)
    updater_thread.start()
    requirements = dependency_check()
    for res in requirements:
        if res['found'] == "not installed":
            message = ('Cannot import {name} module, it is needed to run Bookhouse, '
                       'please install it using "pip install {name}"').format(name=res["name"])
            log.info(message)
            print("*** " + message + " ***")
            web_server.stop(True)
            sys.exit(8)
    for res in requirements + dependency_check(True):
        log.info('*** "{}" version does not meet the requirements. '
                 'Should: {}, Found: {}, please consider installing required version ***'
                 .format(res['name'],
                         res['target'],
                         res['found']))
    app.wsgi_app = ReverseProxied(app.wsgi_app)
    if not hasattr(app, "theme_manager"):
        themes_extension.init_themes(app)

    # Bookhouse: Calibre libraries are strictly read-only. The legacy custom
    # column settings required Calibre DB writes and are forced off.
    config.config_read_column = 0
    config.config_restricted_column = 0

    if os.environ.get('FLASK_DEBUG'):
        cache_buster.init_cache_busting(app)
    log.info('Starting Bookhouse...')
    Principal(app)
    lm.init_app(app)
    app.secret_key = os.getenv('SECRET_KEY', config_sql.get_flask_session_key(ub.session))

    web_server.init_app(app, config)
    from .cw_babel import babel, get_locale
    if hasattr(babel, "localeselector"):
        babel.init_app(app)
        babel.localeselector(get_locale)
    else:
        babel.init_app(app, locale_selector=get_locale)

    from . import services

    if services.ldap:
        services.ldap.init_app(app, config)
    if services.goodreads_support:
        services.goodreads_support.connect(config.config_goodreads_api_key,
                                           config.config_use_goodreads)
    config.store_calibre_uuid(calibre_db, db.Library_Id)
    # Configure rate limiter
    # https://limits.readthedocs.io/en/stable/storage.html
    app.config.update(RATELIMIT_ENABLED=config.config_ratelimiter)
    if config.config_limiter_uri != "" and not cli_param.memory_backend:
        app.config.update(RATELIMIT_STORAGE_URI=config.config_limiter_uri)
        if config.config_limiter_options != "":
            app.config.update(RATELIMIT_STORAGE_OPTIONS=config.config_limiter_options)
    try:
        limiter.init_app(app)
    except Exception as e:
        log.error('Wrong Flask Limiter configuration, falling back to default: {}'.format(e))
        app.config.update(RATELIMIT_STORAGE_URI=None)
        limiter.init_app(app)

    # Register scheduled tasks
    from .schedule import register_scheduled_tasks, register_startup_tasks
    register_scheduled_tasks(config.schedule_reconnect)
    register_startup_tasks()

    return app


# Bookhouse: app.db models whose rows are scoped by library_id
# (ub models are only available after import; resolve at import end)
LIBRARY_ID_TABLES_MODELS = (ub.BookShelf, ub.ReadBook, ub.Bookmark,
                            ub.ArchivedBook, ub.KoboSyncedBooks,
                            ub.KoboReadingState, ub.Downloads)

# fresh-deployment wizard guard (needs app + templates to exist)
initialize_first_library_guard(app)
