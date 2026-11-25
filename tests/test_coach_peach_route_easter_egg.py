"""Exercise the actual Coach Peach route body offline.

Extracts the Flask handler via AST; no app startup,
real authentication, network, database, or AI calls.
"""

import ast
import copy
import sys
import unittest

from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"

tree = ast.parse(APP.read_text(), filename=str(APP))

matches = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "coach_peach_help_api"
]

assert len(matches) == 1

handler = copy.deepcopy(matches[0])
handler.decorator_list = []

module_ast = ast.fix_missing_locations(
    ast.Module(body=[handler], type_ignores=[])
)

HANDLER_CODE = compile(module_ast, str(APP), "exec")


class FakeResponse(dict):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {}


def module(name, **symbols):
    result = ModuleType(name)
    result.__dict__.update(symbols)
    return result


class CoachPeachRouteTests(unittest.TestCase):

    def invoke(
        self,
        question,
        *,
        language="EN",
        identity=(1, 1, 1),
        csrf=True,
        settings=("approved-test-model", 1),
        valid_json=True,
    ):
        calls = []

        def fake_execute(**kwargs):
            calls.append(kwargs)
            return {
                "answer": "NORMAL HELP RESPONSE",
                "articles": [
                    {
                        "page_key": "approved_test_article",
                        "title": "Approved Test Article",
                    }
                ],
            }

        def forbidden_db():
            raise AssertionError(
                "Unexpected database connection"
            )

        request = SimpleNamespace(
            is_json=valid_json,
            content_length=128,
            headers={"X-CSRF-Token": "valid"},
            get_json=lambda silent=True: {
                "question": question,
            },
        )

        namespace = {
            "request": request,
            "jsonify": FakeResponse,
            "_coach_peach_help_identity": lambda: identity,
            "_security_form_csrf_valid": (
                lambda token: csrf and token == "valid"
            ),
            "_coach_peach_help_settings": lambda: settings,
            "get_current_language": lambda: language,
            "get_db_connection": forbidden_db,
        }

        fake_modules = {
            "services.psp_ai_budget_gateway": module(
                "services.psp_ai_budget_gateway",
                AIBudgetError=type(
                    "AIBudgetError", (Exception,), {}
                ),
            ),
            "services.psp_ai_help_context": module(
                "services.psp_ai_help_context",
                AIHelpContextError=type(
                    "AIHelpContextError", (Exception,), {}
                ),
            ),
            "services.psp_ai_help_request": module(
                "services.psp_ai_help_request",
                AIHelpRequestError=type(
                    "AIHelpRequestError", (Exception,), {}
                ),
            ),
            "services.psp_ai_help_execution": module(
                "services.psp_ai_help_execution",
                AIHelpExecutionError=type(
                    "AIHelpExecutionError", (Exception,), {}
                ),
                execute_ai_help=fake_execute,
            ),
            "services.psp_ai_help_provider": module(
                "services.psp_ai_help_provider",
                request_openai_help=lambda **kwargs: (
                    None
                ),
            ),
        }

        with patch.dict(sys.modules, fake_modules):
            exec(HANDLER_CODE, namespace)
            response = namespace[
                "coach_peach_help_api"
            ]()

        return response, calls

    def test_old_fashioned_without_ai(self):
        response, calls = self.invoke(
            "How do I make an Old Fashioned?"
        )
        self.assertTrue(response["success"])
        self.assertIn("Angostura", response["answer"])
        self.assertEqual(response["articles"], [])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(calls, [])

    def test_cocktail_without_ai(self):
        response, calls = self.invoke(
            "Can you suggest a cocktail?"
        )
        self.assertIn("Peachy Bourbon Sour", response["answer"])
        self.assertEqual(calls, [])

    def test_happy_hour_without_ai(self):
        response, calls = self.invoke(
            "Is it happy hour yet?"
        )
        self.assertIn("Cheers", response["answer"])
        self.assertEqual(calls, [])

    def test_spanish_easter_egg_without_ai(self):
        response, calls = self.invoke(
            "¿Ya es la hora feliz?",
            language="ES",
        )
        self.assertIn("¡Salud", response["answer"])
        self.assertEqual(calls, [])

    def test_business_question_uses_normal_help(self):
        response, calls = self.invoke(
            "How do I schedule a Happy Hour event?"
        )
        self.assertEqual(
            response["answer"],
            "NORMAL HELP RESPONSE",
        )
        self.assertEqual(len(calls), 1)

    def test_food_truck_question_uses_normal_help(self):
        response, calls = self.invoke(
            "Can I manage four food trucks?"
        )
        self.assertEqual(
            response["answer"],
            "NORMAL HELP RESPONSE",
        )
        self.assertEqual(len(calls), 1)

    def test_no_identity_blocks_easter_egg(self):
        response, calls = self.invoke(
            "Is it happy hour yet?",
            identity=None,
        )
        self.assertEqual(response[1], 403)
        self.assertEqual(calls, [])

    def test_invalid_csrf_blocks_easter_egg(self):
        response, calls = self.invoke(
            "Is it happy hour yet?",
            csrf=False,
        )
        self.assertEqual(response[1], 403)
        self.assertEqual(calls, [])

    def test_disabled_ai_blocks_easter_egg(self):
        response, calls = self.invoke(
            "Is it happy hour yet?",
            settings=None,
        )
        self.assertEqual(response[1], 503)
        self.assertEqual(calls, [])

    def test_invalid_question_blocks_easter_egg(self):
        response, calls = self.invoke("x")
        self.assertEqual(response[1], 400)
        self.assertEqual(calls, [])

    def test_invalid_json_blocks_easter_egg(self):
        response, calls = self.invoke(
            "Is it happy hour yet?",
            valid_json=False,
        )
        self.assertEqual(response[1], 400)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
