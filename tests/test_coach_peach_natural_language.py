"""Coach Peach natural-language retrieval regression tests.

Offline synthetic fixtures only.
No database, AI provider, network, or payment access.
"""

import unittest

from services.psp_ai_help_search import search_ai_help_articles


def article(page_key, title, keywords="", summary="", content="", language="EN"):
    return {
        "page_key": page_key,
        "title": title,
        "display_name": title,
        "search_keywords": keywords,
        "summary": summary,
        "content": content,
        "language_code": language,
    }


EN_ARTICLES = [
    article(
        "square_overview",
        "Connecting and Using Square with Peach Suite Pro",
        "Peach Suite Pro, Square, manage accounts, enter payments",
        "Peach Suite Pro helps you manage Square transactions.",
    ),
    article(
        "about_peach_suite_pro",
        "About Peach Suite Pro",
        "Peach Suite Pro, accounts, workspaces, business management",
        "Peach Suite Pro provides tools to manage your business.",
    ),
    article(
        "peachpos-managing-event-units",
        "Managing Event Units in PeachPOS",
        "food truck, multiple trucks, event units, trailers, carts",
        "Register and manage multiple mobile operating units.",
        "Businesses with several food trucks can assign each truck "
        "to different events and locations.",
    ),
    article(
        "peachpos-event-calendar",
        "Using the PeachPOS Event Calendar",
        "event calendar, truck schedules, event units, locations",
        "Schedule physical units at events.",
    ),
]

ES_ARTICLES = [
    article(
        "peachpos-creating-managing-events",
        "Crear y administrar eventos en PeachPOS",
        "PeachPOS, eventos, camiones, programación, administrar",
        "Crear eventos y organizar horarios de operación.",
        language="ES",
    ),
    article(
        "peachpos-managing-event-units",
        "Administrar unidades de eventos en PeachPOS",
        "camión de comida, unidades, camiones, equipos móviles",
        "Registrar y administrar varias unidades operativas.",
        "Un negocio puede administrar varios camiones y "
        "asignarlos a diferentes eventos.",
        language="ES",
    ),

    article(
        "peachpos-event-calendar",
        "Cómo utilizar el calendario de eventos de PeachPOS",
        "eventos, calendario, camiones, comida",
        "Programar camiones de comida en eventos.",
        language="ES",
    ),
    article(
        "finding_missing_archived_records",
        "Cómo encontrar registros perdidos, archivados o inactivos",
        "registros, archivados, registros perdidos",
        "Cómo localizar registros de empleados y clientes.",
        language="ES",
    ),
    article(
        "manage_subscription_billing",
        "Cómo administrar su suscripción, prueba gratuita y facturación",
        "suscripción, prueba gratuita, facturación",
        "Administrar suscripción y facturación.",
        language="ES",
    ),
]


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    def execute(self, sql, params):
        self.sql = sql

        for required in (
            "FROM help_pages",
            "spa_id IS NULL",
            "is_active = TRUE",
            "page_key <> 'sms_email_terms'",
        ):
            assert required in sql, (
                f"Missing approved-article restriction: {required}"
            )

    def fetchall(self):
        return self.rows


class CoachPeachRetrievalTests(unittest.TestCase):

    def search(self, question, language="EN"):
        rows = ES_ARTICLES if language == "ES" else EN_ARTICLES
        cursor = FakeCursor(rows)

        return search_ai_help_articles(
            cursor,
            question=question,
            language=language,
            limit=5,
        )

    def test_english_four_trucks_without_feature_name(self):
        results = self.search(
            "I have 4 food trucks, and Peach Suite Pro manage "
            "all 4 and if so, how do I enter and manage them"
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "peachpos-managing-event-units",
        )

    def test_english_explicit_event_units(self):
        results = self.search(
            "How do I manage four food trucks using Event Units?"
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "peachpos-managing-event-units",
        )

    def test_spanish_four_trucks(self):
        results = self.search(
            "Tengo cuatro camiones de comida. "
            "¿Puedo administrar todos en PeachPOS y cómo "
            "los registro?",
            language="ES",
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "peachpos-managing-event-units",
        )

    def test_square_question_remains_relevant(self):
        results = self.search(
            "How do I connect and use Square?"
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "square_overview",
        )

    def test_unrelated_question_returns_no_results(self):
        results = self.search(
            "How do I make an Old Fashioned cocktail?"
        )
        self.assertEqual(results, [])


    def test_spanish_truck_top_three_are_relevant(self):
        results = self.search(
            "Tengo cuatro camiones de comida. "
            "¿Puedo administrar todos en PeachPOS "
            "y cómo los registro?",
            language="ES",
        )
        self.assertEqual(
            [r["page_key"] for r in results[:3]],
            [
                "peachpos-managing-event-units",
                "peachpos-creating-managing-events",
                "peachpos-event-calendar",
            ],
        )

    def test_spanish_archived_records_still_work(self):
        results = self.search(
            "¿Cómo encuentro mis registros archivados?",
            language="ES",
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "finding_missing_archived_records",
        )

    def test_spanish_subscription_still_works(self):
        results = self.search(
            "¿Cómo administrar mi suscripción y facturación?",
            language="ES",
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "manage_subscription_billing",
        )


if __name__ == "__main__":
    unittest.main()
