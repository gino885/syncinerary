import Foundation

/// One data-source credit a transit provider's licence requires.
///
/// The server decides which credits are owed, because it is the only side
/// that knows which providers answered. The app never learns which provider
/// routed a given leg, and does not need to: a leg is routed or approximate.
struct TransitAttribution: Decodable, Sendable, Identifiable {
    var id: String { text }

    let text: String
    let url: URL?
}

struct ItineraryResponse: Decodable, Sendable {
    let versionID: UUID
    let versionNo: Int
    let status: String
    let days: [ItineraryDay]
    let narrative: String?
    let wishlistNotPlaced: [WishlistItem]
    let transitAttributions: [TransitAttribution]

    enum CodingKeys: String, CodingKey {
        case versionID = "version_id"
        case versionNo = "version_no"
        case status
        case days
        case narrative
        case wishlistNotPlaced = "wishlist_not_placed"
        case transitAttributions = "transit_attributions"
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        versionID = try container.decode(UUID.self, forKey: .versionID)
        versionNo = try container.decode(Int.self, forKey: .versionNo)
        status = try container.decode(String.self, forKey: .status)
        days = try container.decode([ItineraryDay].self, forKey: .days)
        narrative = try container.decodeIfPresent(String.self, forKey: .narrative)
        wishlistNotPlaced = try container.decode([WishlistItem].self, forKey: .wishlistNotPlaced)
        // Absent on itineraries planned before credits were carried in the
        // response. An empty list is the honest reading: nothing is owed that
        // the server told us about.
        transitAttributions =
            try container.decodeIfPresent([TransitAttribution].self, forKey: .transitAttributions)
            ?? []
    }
}
