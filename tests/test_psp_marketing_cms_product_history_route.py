"""Offline product history and restore integration tests. No real database."""
import ast
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'app.py').read_text())


def extracted(name, env):
    nodes = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(nodes) != 1:
        raise AssertionError('Missing or duplicate route ' + name)
    node = copy.deepcopy(nodes[0])
    decorators = [ast.unparse(x) for x in node.decorator_list]
    assert decorators[1:] == ['login_required', 'master_admin_required'], decorators
    assert len(decorators) == 3
    node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 'app.py', 'exec'), env)
    return env[name]


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.sql = ''
        self.params = None
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False
    def execute(self, sql, params):
        self.sql = sql
        self.params = params
    def fetchall(self): return self.rows


class Response:
    def __init__(self, body):
        self.body = body
        self.headers = {}


class ProductHistoryRouteTests(unittest.TestCase):
    def setUp(self):
        self.cursor = FakeCursor([(19, 12, 10, 'publish', 7),
                                  (17, 10, None, 'publish', 7)])
        self.conn = SimpleNamespace(cursor=lambda: self.cursor,
                                    rollback=Mock(), close=Mock())
        self.render = Mock(return_value='history rendered')
        self.flash = Mock()
        self.abort = Mock(side_effect=lambda code: (_ for _ in ()).throw(ValueError(f'HTTP {code}')))
        self.request = SimpleNamespace(form={})
        self.env = dict(
            get_db_connection=Mock(return_value=self.conn),
            request=self.request,
            session={'user_id': '7'},
            _security_form_csrf_token=lambda: 'csrf-ok',
            _security_form_csrf_valid=lambda token: token == 'csrf-ok',
            flash=self.flash,
            abort=self.abort,
            render_template=self.render,
            url_for=lambda endpoint, **kw: f"/{endpoint}/{kw.get('product_key', '')}",
            redirect=lambda url: 'redirect:' + url,
        )
        self.history = extracted('master_admin_website_product_history', self.env)
        self.restore = extracted('master_admin_website_product_restore_revision', self.env)
        self.state = dict(draft_revision_id=20, draft_content={'private': True},
                          published_revision_id=12, published_content={'published': True})

    def test_history_rejects_invalid_product_before_database(self):
        with self.assertRaisesRegex(ValueError, 'HTTP 404'):
            self.history('unknown')
        self.env['get_db_connection'].assert_not_called()

    def test_history_scopes_sql_to_exact_product(self):
        with patch('services.psp_marketing_cms_service.load_section_state', return_value=self.state), \
             patch('flask.make_response', side_effect=lambda text: Response(text)):
            response = self.history('solo')
        self.assertEqual(self.cursor.params, ('product.solo',))
        self.assertIn('WHERE page_key = %s', self.cursor.sql)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(self.render.call_args.kwargs['current_revision_id'], 12)
        self.assertEqual(len(self.render.call_args.kwargs['history']), 2)
        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_history_empty_is_supported(self):
        self.cursor.rows = []
        with patch('services.psp_marketing_cms_service.load_section_state', return_value=self.state), \
             patch('flask.make_response', side_effect=lambda text: Response(text)):
            self.history('peachpos')
        self.assertEqual(self.render.call_args.kwargs['history'], [])

    def test_history_refuses_inconsistent_published_state(self):
        state = dict(self.state, published_content=None)
        with patch('services.psp_marketing_cms_service.load_section_state', return_value=state):
            with self.assertRaisesRegex(ValueError, 'HTTP 500'):
                self.history('solo')
        self.conn.close.assert_called_once()

    def test_restore_rejects_invalid_product_csrf_confirmation_before_database(self):
        with self.assertRaisesRegex(ValueError, 'HTTP 404'):
            self.restore('bad')
        with self.assertRaisesRegex(ValueError, 'HTTP 400'):
            self.restore('solo')
        self.request.form = {'security_csrf_token': 'csrf-ok', 'restore_confirmation': 'WRONG'}
        with self.assertRaisesRegex(ValueError, 'HTTP 400'):
            self.restore('solo')
        self.env['get_db_connection'].assert_not_called()

    def test_restore_rejects_bad_actor_and_revision_before_database(self):
        self.request.form = {'security_csrf_token': 'csrf-ok',
                             'restore_confirmation': 'RESTORE',
                             'revision_id': 'bad',
                             'expected_published_revision_id': '12'}
        with self.assertRaisesRegex(ValueError, 'HTTP 400'):
            self.restore('solo')
        self.env['session']['user_id'] = True
        with self.assertRaisesRegex(ValueError, 'HTTP 403'):
            self.restore('solo')
        self.env['get_db_connection'].assert_not_called()

    def test_restore_passes_all_scoped_revisions_and_actor(self):
        self.request.form = {'security_csrf_token': 'csrf-ok',
                             'restore_confirmation': 'RESTORE',
                             'revision_id': '10',
                             'expected_published_revision_id': '12'}
        with patch('services.psp_marketing_cms_product_publication.restore_product_revision',
                   return_value={'revision_id': 10}) as service:
            result = self.restore('solo')
        service.assert_called_once_with(
            self.conn, product_key='solo', actor_id=7,
            revision_id=10, expected_published_revision_id=12)
        self.assertTrue(result.startswith('redirect:'))
        self.conn.close.assert_called_once()

    def test_restore_refuses_unpublished_target_without_success(self):
        from services.psp_marketing_cms_product_publication import (
            MarketingCMSUnpublishedProductRevision,
        )
        self.request.form = {'security_csrf_token': 'csrf-ok',
                             'restore_confirmation': 'RESTORE',
                             'revision_id': '9',
                             'expected_published_revision_id': '12'}
        with patch('services.psp_marketing_cms_product_publication.restore_product_revision',
                   side_effect=MarketingCMSUnpublishedProductRevision('not published')):
            self.restore('solo')
        self.assertEqual(self.flash.call_args.args[1], 'error')
        self.conn.close.assert_called_once()

    def test_templates_are_valid_and_links_are_separate(self):
        from jinja2 import Environment
        template = (ROOT / 'templates/master_admin_website_product_history.html').read_text()
        editor = (ROOT / 'templates/master_admin_website_product.html').read_text()
        Environment().parse(template)
        Environment().parse(editor)
        self.assertIn('restore_confirmation', template)
        self.assertIn('security_csrf_token', template)
        self.assertIn('expected_published_revision_id', template)
        self.assertIn('master_admin_website_product_history', editor)

if __name__ == '__main__':
    unittest.main()
