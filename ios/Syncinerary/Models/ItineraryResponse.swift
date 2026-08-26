import Foundation

struct ItineraryResponse: Decodable, Sendable {
    let versionID: UUID
    let versionNo: Int
    let status: String
    let days: [ItineraryDay]
    let narrative: String?
    let wishlistNotPlaced: [WishlistItem]

    enum CodingKeys: String, CodingKey {
        case versionID = "version_id"
        case versionNo = "version_no"
        case status
        case days
        case narrative
        case wishlistNotPlaced = "wishlist_not_placed"
    }
}
