import math


def _to_float(v, default=None):
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def round_down(value, step=None, decimals=2):
    if value is None:
        return None

    if step and step > 0:
        return math.floor(value / step) * step

    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def round_up(value, step=None, decimals=2):
    if value is None:
        return None

    if step and step > 0:
        return math.ceil(value / step) * step

    factor = 10 ** decimals
    return math.ceil(value * factor) / factor


def extract_market_rules(market_info):
    dealing = market_info.get("dealingRules", {})
    instrument = market_info.get("instrument", {})

    min_size = (
        _to_float(dealing.get("minDealSize", {}).get("value"))
        or _to_float(dealing.get("minDealSize"))
        or 0.01
    )

    size_step = (
        _to_float(dealing.get("dealSizeIncrement", {}).get("value"))
        or _to_float(dealing.get("minSizeIncrement", {}).get("value"))
        or _to_float(dealing.get("dealSizeIncrement"))
        or _to_float(dealing.get("minSizeIncrement"))
        or None
    )

    contract_size = (
        _to_float(instrument.get("contractSize"))
        or 1.0
    )

    raw_margin_factor = (
        _to_float(instrument.get("marginFactor"))
        or _to_float(market_info.get("marginFactor"))
        or None
    )

    return {
        "min_size": min_size,
        "size_step": size_step,
        "contract_size": contract_size,
        "raw_margin_factor": raw_margin_factor,
        "instrument_type": instrument.get("type"),
        "margin_factor_unit": instrument.get("marginFactorUnit") or market_info.get("marginFactorUnit"),
    }


def normalize_margin_rate(raw_margin_factor):
    if raw_margin_factor is None:
        return None

    raw = float(raw_margin_factor)
    if raw >= 100:
        return raw / 1000.0
    if raw >= 1:
        return raw / 100.0
    return raw


def extract_leverage_from_preferences(pref_data, instrument_type=None):
    if isinstance(pref_data, dict) and instrument_type:
        leverages = pref_data.get("leverages")
        if isinstance(leverages, dict):
            bucket = leverages.get(str(instrument_type).upper())
            if isinstance(bucket, dict):
                current = _to_float(bucket.get("current"))
                if current and current > 0:
                    return current

    candidates = []

    if isinstance(pref_data, dict):
        for key in [
            "leverages",
            "leverage",
            "defaultLeverage",
            "accountLeverage",
        ]:
            if key in pref_data:
                candidates.append(pref_data.get(key))

        for key in [
            "preferences",
            "tradingPreferences",
            "accountPreferences",
        ]:
            nested = pref_data.get(key)
            if isinstance(nested, dict):
                for nested_key in [
                    "leverages",
                    "leverage",
                    "defaultLeverage",
                    "accountLeverage",
                ]:
                    if nested_key in nested:
                        candidates.append(nested.get(nested_key))

    for candidate in candidates:
        if isinstance(candidate, (int, float, str)):
            value = _to_float(candidate)
            if value and value > 0:
                return value

        if isinstance(candidate, dict):
            for _, nested_value in candidate.items():
                value = _to_float(nested_value)
                if value and value > 0:
                    return value

    return None


def size_for_target_margin(
    *,
    target_margin,
    margin_per_unit,
    min_size,
    size_step=None,
):
    if target_margin is None or target_margin <= 0:
        return {
            "ok": False,
            "reason": "invalid target margin",
        }

    if margin_per_unit is None or margin_per_unit <= 0:
        return {
            "ok": False,
            "reason": "invalid margin per unit",
        }

    raw_size = target_margin / margin_per_unit
    chosen_size = round_down(raw_size, step=size_step, decimals=2)
    if (chosen_size is None or chosen_size <= 0) and raw_size > 0:
        chosen_size = round_up(min_size, step=size_step, decimals=2)

    if chosen_size is None:
        return {
            "ok": False,
            "reason": "cannot round size for target margin",
        }

    chosen_estimated_margin = chosen_size * margin_per_unit
    if chosen_size < min_size:
        return {
            "ok": False,
            "reason": f"chosen_size {chosen_size} < min_size {min_size}",
            "size": chosen_size,
            "estimated_margin": chosen_estimated_margin,
        }

    return {
        "ok": True,
        "size": chosen_size,
        "estimated_margin": chosen_estimated_margin,
        "raw_size": raw_size,
    }


def resolve_margin_context_live(
    entry_price,
    market_info,
    account_preferences,
    leverage_overrides=None,
    margin_to_account_rate=1.0,
):
    if entry_price is None or entry_price <= 0:
        return {
            "ok": False,
            "reason": "invalid entry price",
        }

    rules = extract_market_rules(market_info)
    raw_margin_factor = rules["raw_margin_factor"]
    instrument_type = rules["instrument_type"]
    leverage_overrides = leverage_overrides or {}
    margin_to_account_rate = _to_float(margin_to_account_rate, default=1.0) or 1.0

    margin_rate = normalize_margin_rate(raw_margin_factor)
    margin_per_unit_by_factor = None
    if margin_rate is not None and margin_rate > 0:
        margin_per_unit_by_factor = (
            entry_price
            * rules["contract_size"]
            * margin_rate
            * margin_to_account_rate
        )

    broker_leverage = extract_leverage_from_preferences(
        account_preferences,
        instrument_type=instrument_type,
    )
    override_leverage = _to_float(
        leverage_overrides.get(str(instrument_type).upper())
    ) if instrument_type else None
    leverage = override_leverage if override_leverage and override_leverage > 0 else broker_leverage

    margin_per_unit_by_leverage = None
    if leverage is not None and leverage > 0:
        margin_per_unit_by_leverage = (
            entry_price
            * rules["contract_size"]
            / leverage
            * margin_to_account_rate
        )

    candidates = []
    if margin_per_unit_by_factor is not None and margin_per_unit_by_factor > 0:
        candidates.append({
            "method": "marginFactor",
            "margin_per_unit": margin_per_unit_by_factor,
        })
    if margin_per_unit_by_leverage is not None and margin_per_unit_by_leverage > 0:
        candidates.append({
            "method": "accountLeverage",
            "margin_per_unit": margin_per_unit_by_leverage,
        })

    preferred_method = None
    if override_leverage and override_leverage > 0:
        preferred_method = "accountLeverage"
    elif broker_leverage and broker_leverage > 0:
        preferred_method = "accountLeverage"

    chosen_candidate = None
    if preferred_method:
        chosen_candidate = next(
            (candidate for candidate in candidates if candidate["method"] == preferred_method),
            None,
        )
    if chosen_candidate is None and candidates:
        chosen_candidate = candidates[0]

    if chosen_candidate is None:
        return {
            "ok": False,
            "reason": "cannot calculate margin per unit from marginFactor or leverage",
            "rules": rules,
            "margin_rate": margin_rate,
            "leverage": leverage,
            "broker_leverage": broker_leverage,
            "override_leverage": override_leverage,
            "raw_margin_factor": raw_margin_factor,
            "instrument_type": instrument_type,
            "margin_to_account_rate": margin_to_account_rate,
            "margin_per_unit_by_factor": margin_per_unit_by_factor,
            "margin_per_unit_by_leverage": margin_per_unit_by_leverage,
        }

    return {
        "ok": True,
        "method": chosen_candidate["method"],
        "margin_per_unit": chosen_candidate["margin_per_unit"],
        "rules": rules,
        "raw_margin_factor": raw_margin_factor,
        "margin_rate": margin_rate,
        "leverage": leverage,
        "broker_leverage": broker_leverage,
        "override_leverage": override_leverage,
        "instrument_type": instrument_type,
        "margin_to_account_rate": margin_to_account_rate,
        "margin_per_unit_by_factor": margin_per_unit_by_factor,
        "margin_per_unit_by_leverage": margin_per_unit_by_leverage,
    }


def choose_size_for_target_margin_live(
    entry_price,
    market_info,
    account_preferences,
    target_margin,
    leverage_overrides=None,
    margin_to_account_rate=1.0,
):
    context = resolve_margin_context_live(
        entry_price=entry_price,
        market_info=market_info,
        account_preferences=account_preferences,
        leverage_overrides=leverage_overrides,
        margin_to_account_rate=margin_to_account_rate,
    )
    if not context.get("ok"):
        return context

    rules = context["rules"]
    sizing_result = size_for_target_margin(
        target_margin=target_margin,
        margin_per_unit=context["margin_per_unit"],
        min_size=rules["min_size"],
        size_step=rules["size_step"],
    )
    if not sizing_result.get("ok"):
        return {
            **context,
            **sizing_result,
        }

    size_by_margin_factor = None
    estimated_margin_by_factor = None
    if context.get("margin_per_unit_by_factor"):
        factor_result = size_for_target_margin(
            target_margin=target_margin,
            margin_per_unit=context["margin_per_unit_by_factor"],
            min_size=rules["min_size"],
            size_step=rules["size_step"],
        )
        size_by_margin_factor = factor_result.get("size")
        estimated_margin_by_factor = factor_result.get("estimated_margin")

    size_by_leverage = None
    estimated_margin_by_leverage = None
    if context.get("margin_per_unit_by_leverage"):
        leverage_result = size_for_target_margin(
            target_margin=target_margin,
            margin_per_unit=context["margin_per_unit_by_leverage"],
            min_size=rules["min_size"],
            size_step=rules["size_step"],
        )
        size_by_leverage = leverage_result.get("size")
        estimated_margin_by_leverage = leverage_result.get("estimated_margin")

    return {
        **context,
        **sizing_result,
        "size_by_margin_factor": size_by_margin_factor,
        "estimated_margin_by_factor": estimated_margin_by_factor,
        "size_by_leverage": size_by_leverage,
        "estimated_margin_by_leverage": estimated_margin_by_leverage,
    }
