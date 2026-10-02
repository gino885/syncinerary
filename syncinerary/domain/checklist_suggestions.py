"""Conservative localized preparation checks, never booking claims."""

from syncinerary.config.locales import normalize_output_locale
from syncinerary.domain.checklist import ChecklistItem
from syncinerary.domain.models import CandidatePlace, CandidateType, Trip

TEXT = {
    "en": (
        "Check transport / train tickets: {name}",
        "Confirm hotel bookings",
        "Check admission / reservations: {name}",
        "Check restaurant reservation: {name}",
    ),
    "zh-Hant": (
        "確認交通／火車票：{name}",
        "確認住宿預訂",
        "確認門票／預約：{name}",
        "確認餐廳訂位：{name}",
    ),
    "zh-Hans": (
        "确认交通／火车票：{name}",
        "确认住宿预订",
        "确认门票／预约：{name}",
        "确认餐厅订位：{name}",
    ),
    "ja": (
        "交通・鉄道のチケットを確認：{name}",
        "宿泊予約を確認",
        "入場券・予約を確認：{name}",
        "レストランの予約を確認：{name}",
    ),
}
TICKET_CATEGORIES = {"museum", "zoo", "aquarium", "amusement_park", "theme_park", "art_gallery"}


def suggestions(trip: Trip, scheduled: list[CandidatePlace]) -> list[ChecklistItem]:
    transfer, hotel, admission, restaurant = TEXT[normalize_output_locale(trip.output_locale)]
    result = [ChecklistItem(trip_id=trip.id, title=hotel, source_key="hotel")]
    for origin, destination in zip(trip.cities, trip.cities[1:]):
        result.append(
            ChecklistItem(
                trip_id=trip.id,
                title=transfer.format(name=f"{origin} → {destination}")[:200],
                source_key=f"transfer:{origin}:{destination}"[:300],
            )
        )
    for place in scheduled:
        if place.reservation_required or place.category in TICKET_CATEGORIES:
            template = restaurant if place.type is CandidateType.FOOD else admission
            result.append(
                ChecklistItem(
                    trip_id=trip.id,
                    title=template.format(name=place.name_canonical)[:200],
                    source_key=f"place:{place.id}",
                )
            )
    return result
