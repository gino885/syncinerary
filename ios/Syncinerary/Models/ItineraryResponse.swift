import Foundation

struct ItineraryResponse: Decodable, Sendable {
    let versionID: UUID
    let versionNo: Int
    let status: String
    let days: [ItineraryDay]
    let narrative: String?
    let wishlistNotPlaced: [WishlistItem]
}
