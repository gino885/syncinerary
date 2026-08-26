import Foundation

struct VoteRequest: Encodable, Sendable {
    let travelerID: UUID
    let candidateID: UUID
    let signal: VoteSignal

    enum CodingKeys: String, CodingKey {
        case travelerID = "traveler_id"
        case candidateID = "candidate_id"
        case signal
    }
}
