import Foundation

struct ItineraryPlaceOption: Decodable, Identifiable, Sendable {
    var id: String { candidateID?.uuidString ?? placeID ?? name }
    let candidateID: UUID?
    let placeID: String?
    let name: String
    let city: String?
    let durationMinutes: Int
    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id", placeID = "place_id", name, city
        case durationMinutes = "duration_minutes"
    }
}
