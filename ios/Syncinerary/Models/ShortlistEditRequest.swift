import Foundation

struct ShortlistEditRequest: Encodable, Sendable {
    let travelerID: UUID
    let selectedCandidateIDs: [UUID]
    let mustGoCandidateIDs: [UUID]

    enum CodingKeys: String, CodingKey {
        case travelerID = "traveler_id"
        case selectedCandidateIDs = "selected_candidate_ids"
        case mustGoCandidateIDs = "must_go_candidate_ids"
    }
}
