"""Isolated route-level checks for product draft publication; no PSP app import or DB."""
import ast
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.psp_marketing_cms_product_baseline import get_product_baseline

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text()
TREE = ast.parse(APP)


def extracted(name, env):
    hits = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(hits) != 1:
        raise AssertionError("Missing or duplicated route: " + name)
    node = copy.deepcopy(hits[0])
    if len(node.decorator_list) != 3:
        raise AssertionError("Missing authentication / Master Admin decorators")
    decorators = [ast.unparse(d) for d in node.decorator_list]
    assert decorators[1:] == ["login_required", "master_admin_required"], decorators
    node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 "app.py", "exec"), env)
    return env[name]


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.headers = {}


class ProductPublishRouteTests(unittest.TestCase):
    def setUp(self):
        self.conn = SimpleNamespace(rollback=Mock(), close=Mock())
        self.flash = Mock()
        self.render = Mock(return_value="private review")
        self.abort = Mock(side_effect=lambda status: (_ for _ in ()).throw(ValueError(f"HTTP {status}")))
        self.request = SimpleNamespace(form={})
        self.env = dict(
            get_db_connection=Mock(return_value=self.conn),
            url_for=lambda name, **kw: f"/{name}/{kw.get('product_key', '')}",
            redirect=lambda url: "redirect:" + url,
            render_template=self.render,
            flash=self.flash,
            abort=self.abort,
            session={"user_id": "7"},
            request=self.request,
            _security_form_csrf_token=lambda: "csrf-secret",
            _security_form_csrf_valid=lambda value: value == "csrf-secret",
        )
        self.review = extracted("master_admin_website_product_publish_review", self.env)
        self.publish = extracted("master_admin_website_product_publish_draft", self.env)

    def test_review_denies_unknown_product_before_db(self):
        with self.assertRaisesRegex(ValueError, "HTTP 404"):
            self.review("unknown")
        self.env["get_db_connection"].assert_not_called()

    def test_review_redirects_without_saved_draft(self):
        state = dict(draft_revision_id=None, draft_content=None,
                     published_revision_id=None, published_content=None)
        with patch("services.psp_marketing_cms_service.load_section_state", return_value=state):
            result = self.review("solo")
        self.assertTrue(result.startswith("redirect:"))
        self.render.assert_not_called()
        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_review_renders_only_private_saved_draft(self):
        state = dict(draft_revision_id=3, draft_content=get_product_baseline("solo"),
                     published_revision_id=None, published_content=None)
        with patch("services.psp_marketing_cms_service.load_section_state", return_value=state), \
             patch("flask.make_response", side_effect=lambda text: FakeResponse(text)):
            result = self.review("solo")
        self.assertEqual(result.headers["Cache-Control"], "private, no-store, max-age=0")
        self.assertEqual(self.render.call_args.args[0],
                         "master_admin_website_product_publish_review.html")
        kw = self.render.call_args.kwargs
        self.assertEqual(kw["draft_revision_id"], 3)
        self.assertIsNone(kw["published_revision_id"])
        self.assertEqual(kw["content"]["shared"]["name"], get_product_baseline("solo")["shared"]["name"])
        self.conn.close.assert_called_once()

    def test_publish_rejects_invalid_product_and_csrf_before_db(self):
        with self.assertRaisesRegex(ValueError, "HTTP 404"):
            self.publish("unknown")
        with self.assertRaisesRegex(ValueError, "HTTP 400"):
            self.publish("solo")
        self.env["get_db_connection"].assert_not_called()

    def test_publish_rejects_confirmation_before_db(self):
        self.request.form = {"security_csrf_token": "csrf-secret",
                             "publish_confirmation": "YES"}
        with self.assertRaisesRegex(ValueError, "HTTP 400"):
            self.publish("solo")
        self.env["get_db_connection"].assert_not_called()

    def test_publish_requires_valid_revision_and_actor_before_db(self):
        self.request.form = {"security_csrf_token": "csrf-secret",
                             "publish_confirmation": "PUBLISH",
                             "expected_draft_revision_id": "not a number",
                             "expected_published_revision_id": ""}
        with self.assertRaisesRegex(ValueError, "HTTP 400"):
            self.publish("solo")
        self.env["session"]["user_id"] = True
        with self.assertRaisesRegex(ValueError, "HTTP 403"):
            self.publish("solo")
        self.env["get_db_connection"].assert_not_called()

    def test_publish_passes_revision_ids_and_actor_to_protected_service(self):
        self.request.form = {"security_csrf_token": "csrf-secret",
                             "publish_confirmation": "PUBLISH",
                             "expected_draft_revision_id": "25",
                             "expected_published_revision_id": "17"}
        with patch("services.psp_marketing_cms_product_publication.publish_product_draft",
                   return_value={"revision_id": 25}) as mocked:
            result = self.publish("team")
        mocked.assert_called_once_with(
            self.conn, product_key="team", actor_id=7,
            expected_draft_revision_id=25,
            expected_published_revision_id=17)
        self.assertTrue(result.startswith("redirect:"))
        self.conn.close.assert_called_once()

    def test_publish_conflict_is_reported_without_success(self):
        from services.psp_marketing_cms_service import MarketingCMSConflict
        self.request.form = {"security_csrf_token": "csrf-secret",
                             "publish_confirmation": "PUBLISH",
                             "expected_draft_revision_id": "25",
                             "expected_published_revision_id": ""}
        with patch("services.psp_marketing_cms_product_publication.publish_product_draft",
                   side_effect=MarketingCMSConflict("stale")):
            result = self.publish("solo")
        self.assertTrue(result.startswith("redirect:"))
        self.flash.assert_called_once()
        self.assertEqual(self.flash.call_args.args[1], "error")
        self.conn.close.assert_called_once()

    def test_html_review_has_separate_confirmed_form(self):
        from jinja2 import Environment
        source = (ROOT / "templates/master_admin_website_product_publish_review.html").read_text()
        Environment().parse(source)
        self.assertIn("expected_published_revision_id", source)
        self.assertIn("expected_draft_revision_id", source)
        self.assertIn("publish_confirmation", source)
        self.assertIn("security_csrf_token", source)
        editor = (ROOT / "templates/master_admin_website_product.html").read_text()
        Environment().parse(editor)
        self.assertIn("master_admin_website_product_publish_review", editor)


if __name__ == "__main__":
    unittest.main()
