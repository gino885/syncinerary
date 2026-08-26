import Foundation

struct WishlistItem: Decodable, Identifiable, Sendable {
    var id: UUID { candidateID }

    let candidateID: UUID
    let name: String
    let reasonCode: String
    let reasonText: String

    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id"
        case name
        case reasonCode = "reason_code"
        case reasonText = "reason_text"
    }
}
