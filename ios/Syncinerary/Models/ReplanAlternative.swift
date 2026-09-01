import Foundation

struct ReplanAlternative: Decodable, Identifiable, Sendable {
    var id: UUID { candidateID }

    let candidateID: UUID
    let score: Double
    let chosen: Bool
    let reason: String?
    let rejectedReason: String?

    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id"
        case score
        case chosen
        case reason
        case rejectedReason = "rejected_reason"
    }
}
