"""Coach Peach Easter egg regression tests.

Offline; no Flask, database, AI, or spending calls.
"""

import unittest

from services.psp_ai_help_easter_eggs import (
    get_coach_peach_easter_egg,
)


class CoachPeachEasterEggTests(unittest.TestCase):

    def test_english_old_fashioned(self):
        answer = get_coach_peach_easter_egg(
            question="How do I make an Old Fashioned?",
            language="EN",
        )
        self.assertIn("Angostura", answer)
        self.assertIn("Old Fashioned", answer)

    def test_english_cocktail(self):
        answer = get_coach_peach_easter_egg(
            question="Can you suggest a cocktail?",
            language="EN",
        )
        self.assertIn("Peachy Bourbon Sour", answer)

    def test_english_happy_hour(self):
        answer = get_coach_peach_easter_egg(
            question="Is it happy hour yet?",
            language="EN",
        )
        self.assertIn("Cheers", answer)

    def test_spanish_old_fashioned(self):
        answer = get_coach_peach_easter_egg(
            question="¿Cómo preparar un Old Fashioned?",
            language="ES",
        )
        self.assertIn("Angostura", answer)
        self.assertIn("¡Salud!", answer)

    def test_spanish_cocktail(self):
        answer = get_coach_peach_easter_egg(
            question="¿Me recomiendas un cóctel?",
            language="ES",
        )
        self.assertIn("durazno", answer)

    def test_spanish_happy_hour(self):
        answer = get_coach_peach_easter_egg(
            question="¿Ya es la hora feliz?",
            language="ES",
        )
        self.assertIn("¡Salud", answer)

    def test_business_questions_not_intercepted(self):
        questions = [
            "How do I add cocktails to my PeachPOS menu?",
            "How do I schedule a Happy Hour event?",
            "Can I sell Old Fashioneds through PeachPOS?",
            "How do I price cocktails for customers?",
            "How do I manage multiple food trucks?",
            "¿Cómo agrego cócteles a mi menú?",
            "¿Cómo programar un evento de hora feliz?",
            "¿Cómo administrar camiones en PeachPOS?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertIsNone(
                    get_coach_peach_easter_egg(
                        question=question,
                        language="ES" if "¿" in question else "EN",
                    )
                )

    def test_additional_business_questions_not_intercepted(self):
        cases = [
            ("How do I add a cocktail as an item?", "EN"),
            ("How do I add cocktails to my offerings?", "EN"),
            ("How do I promote Happy Hour specials?", "EN"),
            ("How do I track cocktail inventory?", "EN"),
            ("¿Cómo agrego cócteles al catálogo?", "ES"),
            ("¿Cómo promocionar la hora feliz?", "ES"),
        ]

        for question, language in cases:
            with self.subTest(question=question):
                self.assertIsNone(
                    get_coach_peach_easter_egg(
                        question=question,
                        language=language,
                    )
                )

    def test_unrelated_questions_not_intercepted(self):
        for question in (
            "How do I send an email?",
            "What is Peach Suite Pro?",
            "How do I reconcile Square payments?",
            "How do I decorate an old-fashioned living room?",
        ):
            with self.subTest(question=question):
                self.assertIsNone(
                    get_coach_peach_easter_egg(
                        question=question,
                        language="EN",
                    )
                )


if __name__ == "__main__":
    unittest.main()
