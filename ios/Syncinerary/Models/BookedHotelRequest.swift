import Foundation

struct BookedHotelRequest: Encodable, Sendable {
    let travelerID: UUID
    let city: String
    let query: String
    let placeID: String

    enum CodingKeys: String, CodingKey {
        case travelerID = "traveler_id"
        case city, query
        case placeID = "place_id"
    }
}
