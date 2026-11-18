import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def make_content(primary):
    return {
        "hero": {
            "primary_button_text": primary,
            "secondary_button_text": "View Pricing",
            "pricing_sentence": (
                "Solo is $49/month or $490/year "
                "after the 10-day free trial."
            ),
        },
    }


class MarketingPublicHomeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path("app.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "route_public_marketing_site"
        ]

        assert len(matches) == 1

        route = matches[0]
        route.decorator_list = []

        cls.code = compile(
            ast.fix_missing_locations(
                ast.Module(
                    body=[route],
                    type_ignores=[],
                )
            ),
            "app.py",
            "exec",
        )

    def render(
        self,
        *,
        state=None,
        host_is_marketing=True,
        method="GET",
        connection_error=False,
    ):
        conn = MagicMock()
        get_connection = MagicMock(return_value=conn)

        if connection_error:
            get_connection.side_effect = RuntimeError(
                "Simulated database outage"
            )

        logger_app = MagicMock()

        namespace = {
            "request": SimpleNamespace(
                host="peachsuitepro.com",
                method=method,
                path="/",
            ),
            "_is_public_marketing_host": (
                lambda host: host_is_marketing
            ),
            "get_db_connection": get_connection,
            "app": logger_app,
            "_public_security_csrf_token": (
                lambda purpose: "test-contact-token"
            ),
            "render_template": (
                lambda name, **kwargs: (name, kwargs)
            ),
        }

        exec(self.code, namespace)

        with patch(
            "services.psp_marketing_cms_service.load_home_state",
            return_value=state,
        ) as loader:
            result = namespace[
                "route_public_marketing_site"
            ]()

        return (
            result,
            conn,
            get_connection,
            loader,
            logger_app,
        )

    def test_published_revision_is_rendered(self):
        published = make_content("Published Home Text")

        result, conn, _, loader, _ = self.render(
            state={
                "draft_content": make_content(
                    "Secret Unpublished Draft"
                ),
                "published_content": published,
            },
        )

        name, context = result

        self.assertEqual(
            name,
            "public_site/psp_home.html",
        )
        self.assertEqual(
            context["cms_home_hero"],
            published["hero"],
        )
        self.assertEqual(
            context["contact_csrf_token"],
            "test-contact-token",
        )
        loader.assert_called_once_with(conn)
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_unpublished_draft_is_never_public(self):
        result, conn, _, _, _ = self.render(
            state={
                "draft_content": make_content(
                    "Secret Unpublished Draft"
                ),
                "published_content": None,
            },
        )

        _, context = result

        self.assertNotIn(
            "cms_home_hero",
            context,
        )
        conn.commit.assert_not_called()

    def test_no_revisions_use_original_wording(self):
        result, _, _, _, _ = self.render(
            state={
                "draft_content": None,
                "published_content": None,
            },
        )

        _, context = result

        self.assertNotIn(
            "cms_home_hero",
            context,
        )

    def test_invalid_published_content_falls_back(self):
        result, conn, _, _, app = self.render(
            state={
                "draft_content": make_content(
                    "Private Draft"
                ),
                "published_content": {
                    "hero": {
                        "primary_button_text": "<script>",
                    }
                },
            },
        )

        _, context = result

        self.assertNotIn(
            "cms_home_hero",
            context,
        )
        app.logger.exception.assert_called()
        conn.close.assert_called_once()

    def test_database_outage_preserves_home_page(self):
        result, _, connector, loader, app = (
            self.render(
                connection_error=True,
            )
        )

        name, context = result

        self.assertEqual(
            name,
            "public_site/psp_home.html",
        )
        self.assertNotIn(
            "cms_home_hero",
            context,
        )
        connector.assert_called_once()
        loader.assert_not_called()
        app.logger.exception.assert_called()

    def test_other_host_never_reads_cms(self):
        result, _, connector, loader, _ = (
            self.render(
                host_is_marketing=False,
            )
        )

        self.assertIsNone(result)
        connector.assert_not_called()
        loader.assert_not_called()

    def test_head_request_reads_published_only(self):
        result, conn, _, _, _ = self.render(
            method="HEAD",
            state={
                "draft_content": make_content(
                    "Secret Draft"
                ),
                "published_content": make_content(
                    "Public Revision"
                ),
            },
        )

        _, context = result

        self.assertEqual(
            context["cms_home_hero"][
                "primary_button_text"
            ],
            "Public Revision",
        )
        conn.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
