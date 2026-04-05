from margin_utils import get_margin_per_unit


def choose_size_for_target_margin(symbol, target_margin):

    margin_per_unit = get_margin_per_unit(symbol)

    if margin_per_unit is None:
        return {
            "size": None,
            "reason": "margin_per_unit unknown"
        }

    size = target_margin / margin_per_unit

    # округляем до 2 знаков
    size = round(size, 2)

    return {
        "size": size,
        "margin_per_unit": margin_per_unit,
        "estimated_margin": size * margin_per_unit,
        "reason": None
    }