from __future__ import annotations
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Dict, Any, Tuple, Optional

from app.models.listings import Listing


@dataclass
class MatchPair:
	Demand: Listing
	Sale: Listing
	score: float


_STOP_WORDS = {
	"и", "или", "для", "на", "в", "из", "с", "к", "по", "от", "до",
	"шт", "штук", "штуки", "б/у", "бу", "новый", "новые", "срочно",
}

_morph = None

def _get_morph():
	global _morph
	if _morph is None:
		try:
			import pymorphy3
			_morph = pymorphy3.MorphAnalyzer()
		except Exception:
			_morph = False
	return _morph


def _tokenize(text: str) -> List[str]:
	lt = (text or "").lower()
	tokens = re.findall(r"[\w\dа-яё]+", lt, flags=re.IGNORECASE)
	# лемматизация
	m = _get_morph()
	if m:
		lemmas = []
		for t in tokens:
			if t in _STOP_WORDS:
				continue
			try:
				lemmas.append(m.parse(t)[0].normal_form)
			except Exception:
				lemmas.append(t)
		return lemmas
	# без морфологии — простая фильтрация стоп-слов
	return [t for t in tokens if t not in _STOP_WORDS]


def _set_jaccard(a: List[str], b: List[str]) -> float:
	sa, sb = set(a), set(b)
	if not sa and not sb:
		return 0.0
	return len(sa & sb) / max(1, len(sa | sb))


def _levenshtein(a: str, b: str) -> int:
	if a == b:
		return 0
	if not a:
		return len(b)
	if not b:
		return len(a)
	prev = list(range(len(b) + 1))
	for i, ca in enumerate(a, start=1):
		cur = [i]
		for j, cb in enumerate(b, start=1):
			cost = 0 if ca == cb else 1
			cur.append(min(
				prev[j] + 1,
				cur[j - 1] + 1,
				prev[j - 1] + cost,
			))
		prev = cur
	return prev[-1]


def _norm_sim(a: str, b: str) -> float:
	"""Нормированное сходство на основе расстояния Левенштейна: 1 - d/max(len)."""
	if not a and not b:
		return 1.0
	maxlen = max(len(a), len(b)) or 1
	return 1.0 - (_levenshtein(a, b) / maxlen)



def _fuzzy_tokens_similarity(a: List[str], b: List[str], *, min_token_similarity: float = 0.6) -> float:
	"""Жадное соответствие токенов по максимальному сходству, симметричное среднее.
	min_token_similarity — минимальная похожесть (0..1), ниже которой совпадение токенов не учитывается.
	"""
	if not a and not b:
		return 0.0
	def best_avr(x: List[str], y: List[str]) -> float:
		if not x:
			return 0.0
		vals: List[float] = []
		for tx in set(x):
			best = 0.0
			for ty in set(y):
				best = max(best, _norm_sim(tx, ty))
			# порог: отбрасываем слабые соответствия
			vals.append(best if best >= min_token_similarity else 0.0)
		return sum(vals) / max(1, len(vals))
	return 0.5 * best_avr(a, b) + 0.5 * best_avr(b, a)


def _price_similarity(d_price: Decimal | None, s_price: Decimal | None, *, price_tolerance_abs: Optional[Decimal] = None, price_tolerance_pct: Optional[float] = None) -> float:
	if d_price is None or s_price is None or d_price <= 0 or s_price <= 0:
		return 0.0
	# допуск: если цена в допуске — считаем близкой (score ~1)
	try:
		delta = abs(Decimal(d_price) - Decimal(s_price))
	except Exception:
		return 0.0
	allow = Decimal(0)
	if price_tolerance_abs:
		allow = max(allow, Decimal(price_tolerance_abs))
	if price_tolerance_pct:
		allow = max(allow, (Decimal(price_tolerance_pct) / Decimal(100)) * Decimal(max(d_price, s_price)))
	if allow > 0 and delta <= allow:
		return 1.0
	# иначе — классическое отношение
	ratio = float(min(d_price, s_price) / max(d_price, s_price))
	return ratio


def _char_similarity(d_char: dict | None, s_char: dict | None) -> float:
	if not d_char or not s_char:
		return 0.0
	d_keys = set(d_char.keys())
	s_keys = set(s_char.keys())
	if not d_keys or not s_keys:
		return 0.0
	key_sim = len(d_keys & s_keys) / max(1, len(d_keys | s_keys))
	val_matches = 0
	common = d_keys & s_keys
	for k in common:
		if str(d_char.get(k)).lower() == str(s_char.get(k)).lower():
			val_matches += 1
	val_sim = val_matches / max(1, len(common)) if common else 0.0
	return 0.5 * key_sim + 0.5 * val_sim


def _location_similarity(d_loc: str | None, s_loc: str | None) -> float:
	if not d_loc or not s_loc:
		return 0.0
	return 1.0 if d_loc.strip().lower() == s_loc.strip().lower() else 0.0


def score_pair(
	demand: Listing,
	sale: Listing,
	*,
	w_title: float = 0.6,
	w_char: float = 0.2,
	w_loc: float = 0.15,
	w_price: float = 0.05,
	price_tolerance_abs: Optional[Decimal] = None,
	price_tolerance_pct: Optional[float] = None,
	# Порог похожести для нечёткого сравнения токенов наименования
	fuzzy_token_threshold: float = 0.6,
) -> float:
	# Комбинируем точечное пересечение и нечёткое сходство
	toks_d = _tokenize(demand.title or "")
	toks_s = _tokenize(sale.title or "")
	jacc = _set_jaccard(toks_d, toks_s)
	fuzzy = _fuzzy_tokens_similarity(toks_d, toks_s, min_token_similarity=fuzzy_token_threshold)
	title_sim = 0.5 * jacc + 0.5 * fuzzy
	char_sim = _char_similarity(demand.characteristics, sale.characteristics)
	loc_sim = _location_similarity(demand.location, sale.location)
	price_sim = _price_similarity(demand.price, sale.price, price_tolerance_abs=price_tolerance_abs, price_tolerance_pct=price_tolerance_pct)
	return w_title * title_sim + w_char * char_sim + w_loc * loc_sim + w_price * price_sim


def find_matches(
	demands: List[Listing],
	sales: List[Listing],
	*,
	threshold: float = 0.45,
	w_title: float = 0.6,
	w_char: float = 0.2,
	w_loc: float = 0.15,
	w_price: float = 0.05,
	price_tolerance_abs: Optional[Decimal] = None,
	price_tolerance_pct: Optional[float] = None,
	fuzzy_token_threshold: float = 0.6,
) -> List[MatchPair]:
	pairs: List[MatchPair] = []
	for d in demands:
		for s in sales:
			score = score_pair(
				d,
				s,
				w_title=w_title,
				w_char=w_char,
				w_loc=w_loc,
				w_price=w_price,
				price_tolerance_abs=price_tolerance_abs,
				price_tolerance_pct=price_tolerance_pct,
				fuzzy_token_threshold=fuzzy_token_threshold,
			)
			if score >= threshold:
				pairs.append(MatchPair(Demand=d, Sale=s, score=score))
	pairs.sort(key=lambda p: p.score, reverse=True)
	return pairs


def title_similarity(a: str | None, b: str | None, *, fuzzy_token_threshold: float = 0.6) -> float:
	"""Публичная функция для оценки похожести наименований.
	Возвращает значение 0..1, комбинируя Jaccard по токенам и нечёткое сопоставление.
	"""
	ad = _tokenize(a or "")
	bd = _tokenize(b or "")
	jacc = _set_jaccard(ad, bd)
	fuzzy = _fuzzy_tokens_similarity(ad, bd, min_token_similarity=fuzzy_token_threshold)
	return 0.5 * jacc + 0.5 * fuzzy


def group_listings(listings: List[Listing]) -> Tuple[List[Listing], List[Listing]]:
	demands: List[Listing] = []
	sales: List[Listing] = []
	for l in listings:
		if (l.type or "").lower() == "demand":
			demands.append(l)
		elif (l.type or "").lower() == "sale":
			sales.append(l)
	return demands, sales