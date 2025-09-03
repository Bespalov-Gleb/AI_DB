from __future__ import annotations
from typing import Iterable, Optional, List
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.listings import Listing
from app.models.photos import Photo
from app.schemas.listing_parse import ParsedListing


def create_listing_from_parsed(session: Session, parsed: ParsedListing) -> Listing:
	if not parsed.title:
		raise ValueError("title is required")
	if not parsed.type:
		raise ValueError("type is required")

	listing = Listing(
		title=parsed.title,
		description=parsed.description,
		characteristics=parsed.characteristics,
		quantity=parsed.quantity,
		price=parsed.price,
		location=parsed.location,
		contact=parsed.contact,
		photo_links=parsed.photo_links,
		type=parsed.type.value if hasattr(parsed.type, "value") else str(parsed.type),
	)
	session.add(listing)
	session.flush()

	_links: Optional[Iterable[str]] = parsed.photo_links
	if _links:
		for link in _links:
			photo = Photo(listing_id=listing.id, s3_key=link, url=link)
			session.add(photo)

	session.commit()
	session.refresh(listing)
	return listing


def list_recent_listings(session: Session, limit: int = 10) -> List[Listing]:
	limit = max(1, limit)  # Убираем ограничение в 50 записей
	return session.query(Listing).order_by(Listing.id.desc()).limit(limit).all()


def delete_listing_by_id(session: Session, listing_id: int) -> bool:
	listing = session.get(Listing, listing_id)
	if not listing:
		return False
	session.delete(listing)
	session.commit()
	return True


def get_all_listings(session: Session) -> List[Listing]:
	return session.query(Listing).order_by(Listing.id.asc()).all()


def get_listings_filtered(
	session: Session,
	city: Optional[str] = None,
	listing_type: Optional[str] = None,
	price_min: Optional[Decimal] = None,
	price_max: Optional[Decimal] = None,
) -> List[Listing]:
	q = session.query(Listing)
	conds = []
	if city:
		conds.append(func.lower(Listing.location) == func.lower(city))
	if listing_type:
		conds.append(Listing.type == listing_type)
	if price_min is not None:
		conds.append(Listing.price >= price_min)
	if price_max is not None:
		conds.append(Listing.price <= price_max)
	if conds:
		q = q.filter(and_(*conds))
	return q.order_by(Listing.id.asc()).all()