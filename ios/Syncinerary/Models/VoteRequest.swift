import Foundation

struct VoteRequest: Encodable, Sendable {
    let travelerID: UUID
    let candidateID: UUID
    let signal: VoteSignal
    let noteText: String?

    init(
        travelerID: UUID,
        candidateID: UUID,
        signal: VoteSignal,
        noteText: String? = nil
    ) {
        self.travelerID = travelerID
        self.candidateID = candidateID
        self.signal = signal
        self.noteText = noteText
    }

    enum CodingKeys: String, CodingKey {
        case travelerID = "traveler_id"
        case candidateID = "candidate_id"
        case signal
        case noteText = "note_text"
    }
}
