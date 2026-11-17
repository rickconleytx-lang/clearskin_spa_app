"""Coach Peach's optional Happy Hour Easter eggs.

Deterministic local responses only.
No database, AI provider, network, or spending calls.
"""

import re
import unicodedata


def _normalize(value):
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(
        c for c in text if not unicodedata.combining(c)
    )
    return " ".join(re.findall(r"[a-z0-9]+", text))


# Business-related questions must continue through normal Help.
BUSINESS_CONTEXT = re.compile(
    r"\b(?:"
    r"peachpos|peachweb|peach suite(?: pro)?|psp|"
    r"menu|menus|business|negocio|negocios|"
    r"event|events|evento|eventos|"
    r"calendar|calendario|schedule|scheduling|"
    r"programar|programacion|"
    r"promotion|promotions|promocion|promociones|"
    r"discount|discounts|descuento|descuentos|"
    r"price|prices|pricing|precio|precios|"
    r"inventory|inventario|product|products|"
    r"producto|productos|"
    r"sale|sales|selling|sell|venta|ventas|vender|"
    r"customer|customers|cliente|clientes|"
    r"employee|employees|empleado|empleados|"
    r"staff|payroll|nomina|"
    r"food truck|truck|trucks|camion|camiones|"
    r"reservation|reservations|booking|"
    r"report|reports|reporte|reportes|"
    r"website|sitio web|"
    r"manage|management|administrar|gestion|"
    r"item|items|articulo|articulos|"
    r"catalog|catalogo|offering|offerings|"
    r"special|specials|promote|promoting|"
    r"promover|promocionar|track|tracking|"
    r"register|registration"
    r")\b"
)


RESPONSES = {
    "EN": {
        "old_fashioned": (
            "Well, sugar, I usually help run businesses, "
            "but I can certainly help you unwind after running one! 🍑🥃\n\n"
            "Coach Peach's Classic Old Fashioned\n\n"
            "2 oz bourbon or rye whiskey\n"
            "1/4 oz simple syrup\n"
            "2 dashes Angostura bitters\n"
            "1 large ice cube\n"
            "Orange peel for garnish\n\n"
            "Stir the whiskey, syrup, and bitters with ice "
            "until chilled. Strain over a large ice cube, "
            "then express the orange peel over the glass.\n\n"
            "Remember, a great cocktail and a well-run business "
            "have something in common: the right ingredients!\n\n"
            "Cheers from Coach Peach! 🍑"
        ),
        "cocktail": (
            "Well, sugar, you've found my secret Happy Hour side! 🍑🍸\n\n"
            "How about a Peachy Bourbon Sour?\n\n"
            "Combine 2 oz bourbon, 1 oz peach nectar, "
            "and 1/2 oz fresh lemon juice. "
            "Shake with ice, strain into a glass, "
            "and garnish with a peach slice.\n\n"
            "Now, what can I help you accomplish in "
            "Peach Suite Pro? 🍑"
        ),
        "happy_hour": (
            "Well, sugar, every hour is a little happier "
            "when your business is running smoothly! 🍑🥂\n\n"
            "If your work is finished, maybe it's time "
            "to kick back and enjoy your favorite drink.\n\n"
            "A well-run business and a great cocktail "
            "have something in common: "
            "it's all about the right ingredients!\n\n"
            "Cheers from Coach Peach! 🍑"
        ),
    },
    "ES": {
        "old_fashioned": (
            "¡Hola! Normalmente te ayudo con tu negocio, "
            "¡pero también conozco la hora feliz! 🍑🥃\n\n"
            "El Old Fashioned clásico de Coach Peach\n\n"
            "2 oz de bourbon o whisky de centeno\n"
            "1/4 oz de jarabe simple\n"
            "2 gotas de amargo Angostura\n"
            "1 cubo grande de hielo\n"
            "Cáscara de naranja para decorar\n\n"
            "Revuelve el whisky, el jarabe y el amargo "
            "con hielo hasta enfriar. Cuela sobre un cubo "
            "grande de hielo y exprime la cáscara de naranja "
            "sobre el vaso.\n\n"
            "Un buen cóctel y un negocio exitoso tienen "
            "algo en común: ¡los ingredientes correctos!\n\n"
            "¡Salud! 🍑"
        ),
        "cocktail": (
            "¡Descubriste mi lado secreto de la hora feliz! 🍑🍸\n\n"
            "¿Qué tal un cóctel de bourbon con durazno?\n\n"
            "Mezcla 2 oz de bourbon, 1 oz de néctar de "
            "durazno y 1/2 oz de jugo de limón fresco. "
            "Agita con hielo, cuela en un vaso y decora "
            "con una rodaja de durazno.\n\n"
            "¡Ahora volvamos a Peach Suite Pro! 🍑"
        ),
        "happy_hour": (
            "¡La hora es más feliz cuando tu negocio "
            "funciona de maravilla! 🍑🥂\n\n"
            "Si ya terminaste tu trabajo, quizás sea "
            "momento de relajarte con tu bebida favorita.\n\n"
            "Un gran negocio y un buen cóctel tienen "
            "algo en común: ¡los ingredientes correctos!\n\n"
            "¡Salud de parte de Coach Peach! 🍑"
        ),
    },
}


def get_coach_peach_easter_egg(*, question, language):
    """Return a localized Easter egg or None.

    Never intercept a recognizable business-management question.
    """
    if not isinstance(question, str):
        return None

    normalized = _normalize(question.strip())

    if not normalized or BUSINESS_CONTEXT.search(normalized):
        return None

    responses = RESPONSES[
        "ES" if language == "ES" else "EN"
    ]

    if re.search(r"\bold fashioned\b", normalized):
        drink_intent = re.search(
            r"\b(?:make|mix|prepare|recipe|drink|"
            r"cocktail|coctel|bourbon|whiskey|whisky|"
            r"hacer|preparar|mezclar|receta)\b",
            normalized,
        )
        if drink_intent or normalized in {
            "old fashioned",
            "an old fashioned",
            "un old fashioned",
        }:
            return responses["old_fashioned"]

    if re.search(r"\b(?:happy hour|hora feliz)\b", normalized):
        return responses["happy_hour"]

    if re.search(
        r"\b(?:cocktail|cocktails|coctel|cocteles|"
        r"mixed drink|tragos)\b",
        normalized,
    ):
        return responses["cocktail"]

    return None
