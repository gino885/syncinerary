import Foundation

struct VoteRequest: Encodable, Sendable {
    let travelerID: UUID
    let candidateID: UUID
    let signal: VoteSignal
}
