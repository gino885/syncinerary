import Foundation

struct SelectItineraryPlaceRequest: Encodable, Sendable {
    let travelerID: UUID
    let day: Int
    let query: String
    let placeID: String
    enum CodingKeys: String, CodingKey {
        case travelerID = "traveler_id", day, query, placeID = "place_id"
    }
}
