import Foundation

struct PreparationLink: Decodable, Sendable, Identifiable {
    let id: UUID
    let travelerID: UUID
    let canonicalURL: String?
    let status: String
    let deferred: Bool?
    enum CodingKeys: String, CodingKey {
        case id, status, deferred
        case travelerID = "traveler_id"
        case canonicalURL = "canonical_url"
    }
}
