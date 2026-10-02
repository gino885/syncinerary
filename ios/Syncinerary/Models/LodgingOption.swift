import Foundation

struct LodgingOption: Decodable, Identifiable, Sendable {
    var id: UUID { candidateID }

    var isBooked: Bool? = nil
    var isSelected: Bool? = nil

    let candidateID: UUID
    let name: String
    let area: String?
    let address: String?
    let priceTier: Int
    let tripStartDate: String
    let tripEndDate: String
    let availabilityNote: String

    enum CodingKeys: String, CodingKey {
        case isBooked = "is_booked"
        case isSelected = "is_selected"
        case candidateID = "candidate_id"
        case name
        case area
        case address
        case priceTier = "price_tier"
        case tripStartDate = "trip_start_date"
        case tripEndDate = "trip_end_date"
        case availabilityNote = "availability_note"
    }
}
