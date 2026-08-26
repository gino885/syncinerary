import Foundation

struct VoteResponse: Decodable, Sendable {
    let id: UUID
    let candidateID: UUID
    let travelerID: UUID
    let signal: String

    enum CodingKeys: String, CodingKey {
        case id
        case candidateID = "candidate_id"
        case travelerID = "traveler_id"
        case signal
    }
}
