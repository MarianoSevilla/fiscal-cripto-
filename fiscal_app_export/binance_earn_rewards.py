"""Diagnóstico conservador de recompensas Simple Earn Flexible.

No une por proximidad ni por valor agregado lotes fiscales. La ausencia de
recompensas Real-time APR en Transaction History es compatible con Binance:
se acumulan en Earn, no se distribuyen a Spot. Los candidatos son solo
evidencia de cantidad; sin hora EUR fiable no son lotes fiscales utilizables.

Sin llamadas externas, almacenamiento, logs de usuario ni emisión de PDF.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re


class BinanceEarnRewardsError(ValueError):
    """Error genérico sin datos de operaciones privadas."""


_KNOWN = {
    "Real-time APR Rewards": "EARN_FLEXIBLE",
    "Bonus Tiered APR Rewards": "SPOT",
    # Recompensa verificada, pero la fuente nativa no acredita destino.
    # Solo un asiento del ledger con cuenta SPOT acredita su recepción.
    "Airdrop Rewards": None,
}
_LEDGER_REWARD = {
    "Simple Earn Flexible Interest": "Bonus Tiered APR Rewards",
    "Simple Earn Flexible Airdrop": "Airdrop Rewards",
}
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,29}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SECOND = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def _asset(value):
    symbol = str(value).strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise BinanceEarnRewardsError("Activo de recompensa no válido")
    return symbol


def _amount(value):
    if isinstance(value, (bool, float)):
        raise BinanceEarnRewardsError("Cantidad de recompensa requiere texto o Decimal")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise BinanceEarnRewardsError("Cantidad de recompensa no válida") from exc
    if not amount.is_finite() or amount <= 0:
        raise BinanceEarnRewardsError("Cantidad de recompensa no positiva o no finita")
    return amount


def _time(value):
    text = str(value).strip()
    try:
        if _DAY.fullmatch(text):
            datetime.strptime(text, "%Y-%m-%d")
            return text, "day"
        if _SECOND.fullmatch(text):
            datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            return text, "second"
    except ValueError:
        pass
    raise BinanceEarnRewardsError("Fecha de recompensa no válida")


@dataclass(frozen=True)
class BinanceEarnRewardCandidate:
    """Una fila nativa, nunca una compra; no se cruza por suma con el ledger."""
    source_ordinal: int
    asset: str
    quantity: Decimal
    earned_on: str
    precision: str
    expected_wallet: str | None
    kind: str
    cost_eur: None = None

    @property
    def acquired_at_for_fifo(self):
        # Una fecha sin hora nunca se transforma en 00:00.
        # Incluso con segundos documentados, falta valorar EUR y validar.
        return None

    @property
    def fiscal_ready(self):
        return False


@dataclass(frozen=True)
class BinanceLedgerEarnRewardEvidence:
    """Apunte de rendimiento del ledger sin identidad nativa unívoca.

    El ledger acredita el abono contable, no su coste EUR ni que la misma
    recompensa deba añadirse por segunda vez al inventario. El ordinal es
    posición de lectura, NO identificador emitido por Binance.
    """
    ledger_ordinal: int
    kind: str  # familia para emparejamiento; NO calificación histórica
    ledger_operation: str  # texto original del asiento, sin reinterpretación
    ledger_time: str
    asset: str
    quantity: Decimal
    wallet: str
    relation: str  # "sin_fuente_nativa" o "solo_total_diario"
    cost_eur: None = None

    @property
    def acquired_at_for_fifo(self):
        return None

    @property
    def fiscal_ready(self):
        return False


@dataclass(frozen=True)
class BinanceEarnRewardsBridge:
    native_records: int
    ledger_records: int
    matched_exact: int
    matched_by_day: int
    daily_aggregate_only_groups: int
    aggregate_only_native_records: int
    aggregate_only_ledger_records: int
    native_not_in_ledger: int
    ledger_not_in_native: int
    repeated_match_records: int
    unknown_native_kinds: int
    native_day_only: int
    auto_subscriptions: int
    candidate_lots: int
    real_time_apr_records: int = 0
    unlocated_native_rewards: int = 0
    # Se conservan todos los apuntes sin match individual: incluso un
    # total diario compatible no prueba identidad, orden ni lote fiscal.
    ledger_unresolved_evidence: tuple[BinanceLedgerEarnRewardEvidence, ...] = ()
    # Solo los NO conciliados ni siquiera por totales diarios.
    ledger_missing_by_year_kind: tuple[tuple[int, str, int], ...] = ()
    native_missing_by_year_kind: tuple[tuple[int, str, int], ...] = ()
    native_day_only_by_year: tuple[tuple[int, int], ...] = ()

    @property
    def fiscal_ready(self):
        # Coincidencias entre informes NO acreditan coste, fecha de devengo
        # intradía, integridad histórica ni tratamiento IRPF.
        return False


def reconcile_earn_rewards(earn_events, ledger_rows):
    """Relaciona evidencias sin eliminar registros ni inventar adquisiciones.

    Prioridad: coincidencia exacta (segundo/activo/cantidad), después fecha
    local/activo/cantidad, y finalmente igualdad de SUMAS diarias en grupos.
    El agregado diario solo informa de compatibilidad aritmética y no de
    identidad uno a uno. La fuente Earn nativa origina candidatos únicos;
    ningún registro espejo del ledger crea un segundo candidato.

    Solo Bonus Tiered y Airdrop se concilian contra tipos EXACTOS del ledger.
    Real-time APR no necesita asiento Spot: no se intenta emparejar con
    "Simple Earn Flexible Interest", ni siquiera si coinciden cantidades.
    Los contadores de ausencias son diagnósticos, NO cierres fiscales.
    """
    native = Counter()
    ledger = Counter()
    candidates = []
    unknown = 0
    auto_subscriptions = 0
    day_only = 0
    native_records = 0
    real_time_records = 0
    unlocated = 0
    native_daily_years = Counter()
    ledger_entries = []

    for ordinal, event in enumerate(earn_events):
        source = str(getattr(event, "source", ""))
        if source == "earn_flexible_subscription":
            kind = str(getattr(event, "kind", "")).strip().casefold()
            if kind.startswith("auto"):
                auto_subscriptions += 1  # Transferencia, NO rendimiento.
            continue
        if source != "earn_flexible_rewards":
            continue
        stamp, precision = _time(event.original_time)
        asset = _asset(event.asset)
        amount = _amount(event.amount)
        kind = str(event.kind).strip()
        native_records += 1
        if precision == "day":
            day_only += 1
            native_daily_years[int(stamp[:4])] += 1
        if kind not in _KNOWN:
            unknown += 1
            continue
        wallet = _KNOWN[kind]
        if kind == "Real-time APR Rewards":
            real_time_records += 1
        else:
            native[(kind, stamp, asset, amount)] += 1
        if wallet is None:
            unlocated += 1
        candidates.append(BinanceEarnRewardCandidate(
            source_ordinal=ordinal,
            asset=asset, quantity=amount, earned_on=stamp,
            precision=precision, expected_wallet=wallet, kind=kind,
        ))

    for ordinal, row in enumerate(ledger_rows):
        kind = _LEDGER_REWARD.get(str(row.get("operación", "")).strip())
        if kind is None:
            continue
        # Un abono en otra custodia no es el espejo Spot de Bonus/Airdrop.
        # Rechazo explícito: no falsear la conciliación por coincidir importe
        # y fecha mientras el destino contable es diferente o desconocido.
        wallet = str(row.get("cuenta", "")).strip()
        if wallet.upper() != "SPOT":
            raise BinanceEarnRewardsError(
                "Billetera de rendimiento Earn del ledger no conciliable"
            )
        stamp, _precision = _time(row.get("tiempo", ""))
        asset = _asset(row.get("moneda", ""))
        amount = _amount(row.get("cambio", ""))
        ledger[(kind, stamp, asset, amount)] += 1
        ledger_entries.append((
            ordinal, kind, str(row.get("operación", "")).strip(),
            stamp, asset, amount, wallet,
        ))

    strict = native & ledger
    exact = sum(strict.values())
    repeated = sum(n for key, n in strict.items()
                   if native[key] > 1 or ledger[key] > 1)
    n_remaining = native - strict
    l_remaining = ledger - strict

    def by_day(counter):
        out = Counter()
        for (kind, stamp, asset, amount), count in counter.items():
            out[(kind, stamp[:10], asset, amount)] += count
        return out

    nday, lday = by_day(n_remaining), by_day(l_remaining)
    daymatched = nday & lday
    matched_by_day = sum(daymatched.values())
    repeated += sum(n for key, n in daymatched.items()
                    if nday[key] > 1 or lday[key] > 1)
    nday.subtract(daymatched)
    lday.subtract(daymatched)
    nday += Counter()
    lday += Counter()

    # Distinto número de filas o distinta descomposición de importes:
    # si cuadra el TOTAL, describirlo como agregado, jamás como match fila.
    def totals(counter):
        out = defaultdict(lambda: [Decimal(0), 0])
        for (kind, day, asset, amount), count in counter.items():
            bucket = out[(kind, day, asset)]
            bucket[0] += amount * count
            bucket[1] += count
        return out

    nsum, lsum = totals(nday), totals(lday)
    aggregate_groups = 0
    agg_native = agg_ledger = 0
    aggregate_keys = set()
    for key in nsum.keys() & lsum.keys():
        if nsum[key][0] == lsum[key][0]:
            aggregate_groups += 1
            aggregate_keys.add(key)
            agg_native += nsum[key][1]
            agg_ledger += lsum[key][1]

    # Relacionar las ocurrencias concretas en el mismo orden del ledger,
    # nunca deduplicarlas por coincidencias de importe/segundo.
    strict_available = strict.copy()
    day_available = daymatched.copy()
    unresolved = []
    missing_year_kind = Counter()
    for ordinal, kind, operation, stamp, asset, amount, wallet in ledger_entries:
        key = (kind, stamp, asset, amount)
        daily_key = (kind, stamp[:10], asset, amount)
        if strict_available[key] > 0:
            strict_available[key] -= 1
        elif day_available[daily_key] > 0:
            day_available[daily_key] -= 1
        else:
            relation = (
                "solo_total_diario"
                if (kind, stamp[:10], asset) in aggregate_keys
                else "sin_fuente_nativa"
            )
            unresolved.append(BinanceLedgerEarnRewardEvidence(
                ledger_ordinal=ordinal, kind=kind, ledger_operation=operation,
                ledger_time=stamp, asset=asset, quantity=amount,
                wallet=wallet, relation=relation,
            ))
            if relation == "sin_fuente_nativa":
                missing_year_kind[(int(stamp[:4]), operation)] += 1

    # Los candidatos de la fuente nativa sin espejo tampoco deben desaparecer.
    # Un match por suma diaria no permite individualizar recompensa y asiento.
    native_missing_year_kind = Counter()
    for (kind, day, asset, _amount), count in nday.items():
        if (kind, day, asset) not in aggregate_keys:
            native_missing_year_kind[(int(day[:4]), kind)] += count

    def grouped_year_kind(counter):
        return tuple(
            (year, kind, count)
            for (year, kind), count in sorted(counter.items())
        )

    if (
        sum(missing_year_kind.values()) != sum(lday.values()) - agg_ledger
        or sum(native_missing_year_kind.values()) != sum(nday.values()) - agg_native
    ):
        raise BinanceEarnRewardsError(
            "Inconsistencia de multiplicidades en conciliación de recompensas"
        )

    return BinanceEarnRewardsBridge(
        native_records=native_records,
        ledger_records=sum(ledger.values()),
        matched_exact=exact,
        matched_by_day=matched_by_day,
        daily_aggregate_only_groups=aggregate_groups,
        aggregate_only_native_records=agg_native,
        aggregate_only_ledger_records=agg_ledger,
        native_not_in_ledger=sum(nday.values()) - agg_native,
        ledger_not_in_native=sum(lday.values()) - agg_ledger,
        repeated_match_records=repeated,
        unknown_native_kinds=unknown,
        native_day_only=day_only,
        auto_subscriptions=auto_subscriptions,
        candidate_lots=len(candidates),
        real_time_apr_records=real_time_records,
        unlocated_native_rewards=unlocated,
        ledger_unresolved_evidence=tuple(unresolved),
        ledger_missing_by_year_kind=grouped_year_kind(missing_year_kind),
        native_missing_by_year_kind=grouped_year_kind(native_missing_year_kind),
        native_day_only_by_year=tuple(sorted(native_daily_years.items())),
    ), tuple(candidates)
