import Foundation

struct VoteResponse: Decodable, Sendable {
    let id: UUID
    let candidateID: UUID
    let travelerID: UUID
    let signal: String
}
